"""Loopback-only web interface; workers continue when the browser closes."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import unquote, urlsplit

import yaml
from job_runner import create_job, launch_worker, atomic_json
from providers import ENDPOINTS, CLOUD_PROVIDERS, MODEL_GROUPS, model_overrides, list_models, list_model_catalog, model_info, api_key_for, openrouter_key_status, provider_key_status, test_openrouter_key, test_provider_key
import credentials
from book_chat import read_messages, progress_messages, reply_to_book
from job_lock import job_lock
from book_library import editor_data, edit_book, continue_book, snapshot, update_model
from pipeline_inspect import inspect_job, artifact_text, prompt_text
import audiobook
import book_video


def read_json(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def validate_settings(data):
    config = model_overrides(data.get('provider'), data.get('model'), data.get('base_url'))
    settings = {**config['connection'], 'model': config['default_model']}
    for key, default, minimum, maximum in (
        ('max_calls_per_job', 200, 1, 10000),
        ('max_output_tokens', 8192, 256, 131072),
        ('timeout_seconds', 900, 30, 10600),
    ):
        value = data.get(key, default)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f'{key} must be a whole number between {minimum} and {maximum}.')
        settings[key] = value
    role_models = data.get('role_models', {})
    if not isinstance(role_models, dict) or set(role_models) - set(MODEL_GROUPS):
        raise ValueError('Role model choices must use the available role groups.')
    settings['role_models'] = {}
    for group in MODEL_GROUPS:
        value = role_models.get(group, '')
        if not isinstance(value, str) or len(value) > 200:
            raise ValueError(f'Model choice for {group} must be a model ID under 200 characters.')
        settings['role_models'][group] = value.strip()
    return settings


def settings_config(settings):
    config = model_overrides(settings['provider'], settings['model'], settings['base_url'])
    config['connection']['timeout_seconds'] = settings['timeout_seconds']
    config.update({key: settings[key] for key in ('max_calls_per_job', 'max_output_tokens')})
    if settings['provider'] in CLOUD_PROVIDERS:
        configured_roles = settings.get('role_models') or {}
        config['role_models'] = {group: configured_roles.get(group) or settings['model'] for group in MODEL_GROUPS}
        config['use_default_model_for_all_services'] = False
    else:
        config['role_models'] = {}
        config['use_default_model_for_all_services'] = True
    return config


class AthenaServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root, port=8765, launcher=launch_worker, audio_launcher=audiobook.launch, film_launcher=book_video.launch):
        self.root = Path(root).resolve()
        self.token = secrets.token_urlsafe(32)
        self.launcher = launcher
        self.audio_launcher = audio_launcher
        self.film_launcher = film_launcher
        self.settings_lock = threading.Lock()
        self.chat_locks = {}
        super().__init__(('127.0.0.1', port), Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def respond(self, data, status=200, content_type='application/json; charset=utf-8', download=False):
        body = json.dumps(data).encode() if content_type.startswith('application/json') else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if download:
            self.send_header('Content-Disposition', 'attachment; filename="manuscript.md"')
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        port = self.server.server_address[1]
        return self.headers.get('Host') in (f'127.0.0.1:{port}', f'localhost:{port}')

    def respond_audio(self, path, content_type='audio/wav'):
        """Stream audio and support browser seeking without loading a book into RAM."""
        size = path.stat().st_size
        start, end, code = 0, size - 1, 200
        requested = self.headers.get('Range')
        if requested:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
            if not match or not any(match.groups()):
                self.send_error(416)
                return
            if match[1]:
                start = int(match[1])
                end = min(int(match[2]), end) if match[2] else end
            else:
                start = max(0, size - int(match[2]))
            if start > end or start >= size:
                self.send_error(416)
                return
            code = 206
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Content-Disposition', f'inline; filename="{path.name}"')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if code == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as stream:
            stream.seek(start)
            remaining = end - start + 1
            try:
                while remaining:
                    block = stream.read(min(65536, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def job_path(self, identifier):
        if not re.fullmatch('[0-9a-f]{32}', identifier):
            raise ValueError('Invalid book ID.')
        path = self.server.root / 'jobs' / identifier
        if not (path / 'job.json').is_file():
            raise FileNotFoundError('Book not found.')
        return path

    def job_info(self, path, detail=False):
        state = read_json(path / 'job.json')
        state['id'] = path.name
        memory = path / '08_Memory'
        state['usage'] = read_json(memory / 'usage.json', {})
        state['pipeline'] = read_json(memory / 'pipeline_state.json', {})
        state['metadata'] = read_json(memory / 'metadata.json', {})
        state['download_ready'] = state['status'] == 'completed' and (memory / 'manuscript.md').exists()
        config = yaml.safe_load((path / 'config/models.yaml').read_text(encoding='utf-8'))
        state['provider'] = config.get('connection', {}).get('provider', 'openrouter')
        state['model'] = config.get('default_model', '')
        state['role_models'] = config.get('role_models', {})
        if detail:
            state['log'] = ''
            if (path / 'worker.log').exists():
                with (path / 'worker.log').open('rb') as stream:
                    stream.seek(0, 2)
                    stream.seek(max(0, stream.tell() - 16000))
                    state['log'] = stream.read().decode('utf-8', errors='replace')
            state['activity'] = progress_messages(state, state['log'])
            state['conversation'] = read_messages(path)
            state['chat_usage'] = read_json(memory / 'chat_usage.json', {})
        return state

    def do_GET(self):
        if not self.valid_host():
            self.respond({'error': 'Invalid host.'}, 403)
            return
        path = urlsplit(self.path).path
        try:
            static = {'/': ('index.html', 'text/html'), '/settings': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
            static['/settings.css'] = ('settings.css', 'text/css')
            static['/chat.css'] = ('chat.css', 'text/css')
            static['/polish.css'] = ('polish.css', 'text/css')
            static['/studio.js'] = ('studio.js', 'text/javascript')
            static['/studio.css'] = ('studio.css', 'text/css')
            if re.fullmatch('/books/[0-9a-f]{32}/studio', path):
                static[path] = ('studio.html', 'text/html')
            if re.fullmatch('/books/[0-9a-f]{32}', path):
                static[path] = ('index.html', 'text/html')
            if path in static:
                filename, kind = static[path]
                self.respond((self.server.root / 'ui' / filename).read_bytes(), content_type=kind + '; charset=utf-8')
            elif path == '/api/bootstrap':
                self.respond({'token': self.server.token, 'endpoints': ENDPOINTS})
            elif path == '/api/openrouter-key':
                self.respond(openrouter_key_status(self.server.root))
            elif path == '/api/settings':
                self.respond(read_json(self.server.root / 'config/ui_settings.json', {
                    'provider': 'ollama', 'base_url': ENDPOINTS['ollama'], 'model': '',
                    'max_calls_per_job': 200, 'max_output_tokens': 8192, 'timeout_seconds': 900,
                    'role_models': {},
                }))
            elif path == '/api/narration-settings':
                self.respond(read_json(self.server.root / 'config/narration.json', audiobook.DEFAULTS))
            elif match := re.fullmatch('/api/jobs/([0-9a-f]{32})/pdf', path):
                job = self.job_path(match[1])
                audiobook.studio_data(job)
                from book_pdf import build_pdf
                with job_lock(job):
                    output = build_pdf(job)
                self.respond(output.read_bytes(), content_type='application/pdf')
            elif match := re.fullmatch('/api/jobs/([0-9a-f]{32})/film-status', path):
                job = self.job_path(match[1])
                audiobook.studio_data(job)
                state = book_video.status(job)
                logs = []
                for filename in ('check.log', 'render.log', 'worker.log'):
                    log = job / 'film' / filename
                    if log.exists():
                        with log.open('rb') as stream:
                            stream.seek(0, 2); stream.seek(max(0, stream.tell()-6000))
                            logs.append(stream.read().decode('utf-8', errors='replace'))
                state['log'] = '\n'.join(logs)
                self.respond(state)
            elif match := re.fullmatch('/api/jobs/([0-9a-f]{32})/film/(preview.html|index.html|player.js|storyboard.json|film.mp4|project.zip|assets/character-[0-7][.]svg|assets/chapter-[0-9]{3}[.]wav)', path):
                job = self.job_path(match[1])
                audiobook.studio_data(job)
                state = book_video.status(job)
                if state['status'] == 'stale':
                    raise FileNotFoundError('This video belongs to an earlier book revision. Rebuild it.')
                filename = match[2]
                file = job / 'film' / filename
                if filename == 'film.mp4':
                    if state['status'] != 'completed':
                        raise FileNotFoundError('Render the video before downloading it.')
                    self.respond_audio(file, 'video/mp4')
                elif filename == 'project.zip':
                    import zipfile
                    with job_lock(job):
                        with zipfile.ZipFile(file, 'w', zipfile.ZIP_DEFLATED) as archive:
                            for name in ('index.html', 'preview.html', 'player.js', 'storyboard.json', 'package.json', 'hyperframes.json'):
                                archive.write(job / 'film' / name, name)
                            for asset in (job / 'film/assets').glob('*'):
                                archive.write(asset, 'assets/' + asset.name)
                    self.respond_audio(file, 'application/zip')
                elif filename.endswith('.wav'):
                    self.respond_audio(file)
                elif filename.endswith('.html'):
                    body = file.read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Content-Security-Policy', "default-src 'self' blob: data:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'self'; base-uri 'self'")
                    self.end_headers(); self.wfile.write(body)
                else:
                    kind = 'image/svg+xml' if filename.endswith('.svg') else 'text/javascript' if filename.endswith('.js') else 'application/json'
                    self.respond(file.read_bytes(), content_type=kind if kind != 'application/json' else 'text/plain')
            elif match := re.fullmatch('/api/jobs/([0-9a-f]{32})/(studio|audio-status)', path):
                job = self.job_path(match[1])
                self.respond(audiobook.studio_data(job) if match[2] == 'studio' else audiobook.status(job))
            elif match := re.fullmatch('/api/jobs/([0-9a-f]{32})/audio/([a-z0-9-]+[.]wav)', path):
                job = self.job_path(match[1])
                audio_state = audiobook.status(job)
                allowed = [t['filename'] for t in audio_state['tracks'].values()]
                if audio_state.get('master'):
                    allowed.append(audio_state['master']['filename'])
                if match[2] not in allowed:
                    raise FileNotFoundError('This audio is unavailable or belongs to an earlier manuscript revision.')
                self.respond_audio(job / 'audio' / match[2])
            elif path in ('/api/jobs', '/api/trash'):
                jobs = []
                for state_file in (self.server.root / 'jobs').glob('*/job.json'):
                    try:
                        info = self.job_info(state_file.parent)
                        if bool(info.get('deleted_at')) == (path == '/api/trash'):
                            jobs.append(info)
                    except (ValueError, OSError, yaml.YAMLError):
                        continue
                self.respond(sorted(jobs, key=lambda job: job['created_at'], reverse=True))
            elif match := re.fullmatch('/api/jobs/([0-9a-f]{32})/editor', path):
                self.respond(editor_data(self.job_path(match[1])))
            elif match := re.fullmatch('/api/jobs/([0-9a-f]{32})/inspect', path):
                self.respond(inspect_job(self.job_path(match[1])))
            elif match := re.fullmatch('/api/jobs/([0-9a-f]{32})/artifact/([^/]+)', path):
                # One URL-encoded segment; artifact_text re-validates after decoding.
                self.respond(artifact_text(self.job_path(match[1]), unquote(match[2])).encode('utf-8'),
                             content_type='text/plain; charset=utf-8')
            elif match := re.fullmatch('/api/jobs/([0-9a-f]{32})/prompt/([^/]+)', path):
                # One URL-encoded segment; prompt_text re-validates after decoding.
                self.respond(prompt_text(self.job_path(match[1]), unquote(match[2])).encode('utf-8'),
                             content_type='text/plain; charset=utf-8')
            elif match := re.fullmatch('/api/jobs/([0-9a-f]{32})(/manuscript)?', path):
                job = self.job_path(match[1])
                if match[2]:
                    if not self.job_info(job)['download_ready']:
                        raise FileNotFoundError('The manuscript is not ready yet.')
                    self.respond((job / '08_Memory/manuscript.md').read_bytes(), content_type='text/plain; charset=utf-8', download=True)
                else:
                    self.respond(self.job_info(job, True))
            else:
                self.respond({'error': 'Not found.'}, 404)
        except FileNotFoundError as error:
            self.respond({'error': str(error)}, 404)
        except (ValueError, OSError, yaml.YAMLError) as error:
            self.respond({'error': str(error)}, 400)

    def do_POST(self):
        origin = self.headers.get('Origin')
        if (not self.valid_host() or self.headers.get('X-Athena-Token') != self.server.token
                or (origin and origin != 'http://' + self.headers.get('Host', ''))):
            # Drain small requests before closing so Windows clients receive the
            # 403 response rather than a reset caused by an unread request body.
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if 0 < size <= 65536:
                    self.connection.settimeout(2)
                    self.rfile.read(size)
            except (ValueError, OSError):
                pass
            self.respond({'error': 'Reload Athena before trying again.'}, 403)
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 2097152:
                raise ValueError('Request is empty or too large.')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('Expected a JSON object.')
            path = urlsplit(self.path).path
            if path == '/api/models':
                self.respond({'models': list_models(data.get('provider'), data.get('base_url'), self.server.root)})
            elif path == '/api/model-catalog':
                self.respond({'models': list_model_catalog(data.get('provider'), data.get('base_url'), self.server.root)})
            elif path == '/api/model-info':
                self.respond(model_info(data.get('provider'), data.get('model'), data.get('base_url'), self.server.root))
            elif path == '/api/provider-key':
                provider, action = data.get('provider'), data.get('action')
                if provider not in CLOUD_PROVIDERS:
                    raise ValueError('Choose a cloud provider for API key settings.')
                if action == 'status':
                    self.respond(provider_key_status(provider, self.server.root))
                elif action == 'test':
                    self.respond(test_provider_key(provider, data.get('key'), self.server.root))
                elif action in ('save', 'remove'):
                    with self.server.settings_lock:
                        if action == 'save':
                            try:
                                credentials.save_key(data.get('key'), self.server.root, provider)
                            except TypeError:
                                credentials.save_key(data.get('key'), self.server.root)
                        else:
                            try:
                                credentials.delete_key(self.server.root, provider)
                            except TypeError:
                                credentials.delete_key(self.server.root)
                    self.respond(provider_key_status(provider, self.server.root))
                else:
                    raise ValueError('Choose status, test, save, or remove.')
            elif path == '/api/openrouter-key':
                action = data.get('action')
                if action == 'test':
                    self.respond(test_openrouter_key(data.get('key'), self.server.root))
                elif action in ('save', 'remove'):
                    with self.server.settings_lock:
                        if action == 'save':
                            credentials.save_key(data.get('key'), self.server.root)
                        else:
                            credentials.delete_key(self.server.root)
                    self.respond(openrouter_key_status(self.server.root))
                else:
                    raise ValueError('Choose save, test, or remove.')
            elif match := re.fullmatch('/api/jobs/([0-9a-f]{32})/film', path):
                job = self.job_path(match[1])
                with self.server.settings_lock:
                    with job_lock(job):
                        book_video.prepare(job, data)
                    try:
                        self.server.film_launcher(self.server.root, job)
                    except Exception:
                        state = read_json(job / 'film/state.json')
                        state.update(status='failed', error='Could not launch the video worker. Try again.')
                        atomic_json(job / 'film/state.json', state)
                        raise
                self.respond({'id':job.name}, 202)
            elif path == '/api/narration-settings':
                settings = audiobook.validate_settings(data)
                with self.server.settings_lock:
                    atomic_json(self.server.root / 'config/narration.json', settings)
                self.respond(settings)
            elif match := re.fullmatch('/api/jobs/([0-9a-f]{32})/narrate', path):
                job = self.job_path(match[1])
                with self.server.settings_lock:
                    with job_lock(job):
                        previous = audiobook.status(job)
                        if previous['status'] in ('pending', 'running'):
                            raise ValueError('Narration is already queued or running for this book.')
                        settings = audiobook.validate_settings(data.get('settings', {}))
                        audiobook.prepare(job, settings, data.get('chapters'))
                    try:
                        self.server.audio_launcher(self.server.root, job)
                    except Exception:
                        state = read_json(job / 'audio/state.json')
                        state.update(status='failed', error='Could not launch narration. Try again.')
                        atomic_json(job / 'audio/state.json', state)
                        raise
                self.respond({'id': job.name}, 202)
            elif path == '/api/settings':
                settings = validate_settings(data)
                with self.server.settings_lock:
                    atomic_json(self.server.root / 'config/ui_settings.json', settings)
                self.respond(settings)
            elif path == '/api/jobs':
                concept = data.get('concept', '')
                if not isinstance(concept, str) or not 1 <= len(concept.strip()) <= 30000:
                    raise ValueError('Describe your book in 1–30,000 characters.')
                chapters = data.get('chapters')
                if chapters is not None and (type(chapters) is not int or not 1 <= chapters <= 200):
                    raise ValueError('Choose 1–200 chapters, or leave the length to Athena.')
                if 'provider' in data:
                    config = model_overrides(data.get('provider'), data.get('model'), data.get('base_url'))
                else:
                    settings = read_json(self.server.root / 'config/ui_settings.json')
                    if not settings:
                        raise ValueError('Choose and save your writing model in Settings first.')
                    config = settings_config(validate_settings(settings))
                api_key_for(config['connection']['provider'], self.server.root)  # Fail before creating a cloud job without credentials.
                job = create_job(self.server.root, concept, chapters, config)
                self.server.launcher(self.server.root, job)
                self.respond({'id': job.name}, 201)
            elif match := re.fullmatch('/api/jobs/([0-9a-f]{32})/(resume|edit|continue|delete|restore)', path):
                job = self.job_path(match[1])
                action = match[2]
                with self.server.settings_lock:
                    lock = self.server.chat_locks.setdefault(job.name, threading.Lock())
                if not lock.acquire(blocking=False):
                    raise ValueError('Wait for Athena’s current reply before changing this book.')
                try:
                    with job_lock(job):
                        state = read_json(job / 'job.json')
                        if state.get('deleted_at') and action != 'restore':
                            raise ValueError('Restore this deleted book before changing it.')
                        if action in ('delete', 'restore'):
                            if action == 'delete':
                                state['deleted_at'] = time.time()
                            else:
                                state.pop('deleted_at', None)
                            atomic_json(job / 'job.json', state)
                        elif action == 'edit':
                            edit_book(job, data)
                        else:
                            if action == 'resume' and state['status'] == 'completed':
                                raise ValueError('This book is completed. Add a continuation instead.')
                            if data.get('use_current_settings'):
                                settings = validate_settings(read_json(self.server.root / 'config/ui_settings.json', {}))
                                config = settings_config(settings)
                                if data.get('safer_limits'):
                                    config['max_output_tokens'] = min(config['max_output_tokens'], 4096)
                                api_key_for(config['connection']['provider'], self.server.root)
                                snapshot(job)
                                update_model(job, config)
                            if action == 'continue':
                                continue_book(job, data.get('instructions'), data.get('chapters'))
                    if action in ('resume', 'continue'):
                        self.server.launcher(self.server.root, job)
                finally:
                    lock.release()
                self.respond({'id': job.name})
            elif match := re.fullmatch('/api/jobs/([0-9a-f]{32})/messages', path):
                job = self.job_path(match[1])
                message = data.get('message')
                if not isinstance(message, str) or not 1 <= len(message.strip()) <= 8000:
                    raise ValueError('Write a message between 1 and 8,000 characters.')
                with self.server.settings_lock:
                    lock = self.server.chat_locks.setdefault(job.name, threading.Lock())
                if not lock.acquire(blocking=False):
                    raise ValueError('Athena is still replying to your previous message.')
                try:
                    if read_json(job / 'job.json').get('deleted_at'):
                        raise ValueError('Restore this book before sending a message.')
                    self.respond({'conversation': reply_to_book(job, message)})
                finally:
                    lock.release()
            else:
                self.respond({'error': 'Not found.'}, 404)
        except FileNotFoundError as error:
            self.respond({'error': str(error)}, 404)
        except Exception as error:
            # Provider SDK exceptions are intentionally converted to actionable UI messages.
            message = str(error)
            if urlsplit(self.path).path in ('/api/openrouter-key', '/api/provider-key') and not isinstance(error, (ValueError, RuntimeError)):
                message = 'The key could not be processed. Try again from your normal desktop session.'
            if isinstance(locals().get('data'), dict) and isinstance(data.get('key'), str) and data['key']:
                message = message.replace(data['key'], '[redacted]')
            self.respond({'error': message}, 400)


def serve(root, port=8765):
    server = AthenaServer(root, port)
    print(f'Athena is ready at http://127.0.0.1:{server.server_address[1]}', flush=True)
    print('Leave this terminal open for the UI. Book workers run independently.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
