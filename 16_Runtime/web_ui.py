"""Loopback-only web interface; workers continue when the browser closes."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import urlsplit

import yaml
from job_runner import create_job, launch_worker, atomic_json
from providers import ENDPOINTS, model_overrides, list_models, api_key_for, openrouter_key_status, test_openrouter_key
import credentials
from book_chat import read_messages, progress_messages, reply_to_book


def read_json(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def validate_settings(data):
    config = model_overrides(data.get('provider'), data.get('model'), data.get('base_url'))
    settings = {**config['connection'], 'model': config['default_model']}
    for key, default, minimum, maximum in (
        ('max_calls_per_job', 200, 1, 10000),
        ('max_output_tokens', 8192, 256, 131072),
        ('timeout_seconds', 900, 30, 3600),
    ):
        value = data.get(key, default)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f'{key} must be a whole number between {minimum} and {maximum}.')
        settings[key] = value
    return settings


def settings_config(settings):
    config = model_overrides(settings['provider'], settings['model'], settings['base_url'])
    config['connection']['timeout_seconds'] = settings['timeout_seconds']
    config.update({key: settings[key] for key in ('max_calls_per_job', 'max_output_tokens')})
    return config


class AthenaServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root, port=8765, launcher=launch_worker):
        self.root = Path(root).resolve()
        self.token = secrets.token_urlsafe(32)
        self.launcher = launcher
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
                }))
            elif path == '/api/jobs':
                jobs = []
                for state_file in (self.server.root / 'jobs').glob('*/job.json'):
                    try:
                        jobs.append(self.job_info(state_file.parent))
                    except (ValueError, OSError, yaml.YAMLError):
                        continue
                self.respond(sorted(jobs, key=lambda job: job['created_at'], reverse=True))
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
            if not 0 < size <= 65536:
                raise ValueError('Request is empty or too large.')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('Expected a JSON object.')
            path = urlsplit(self.path).path
            if path == '/api/models':
                self.respond({'models': list_models(data.get('provider'), data.get('base_url'), self.server.root)})
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
            elif match := re.fullmatch('/api/jobs/([0-9a-f]{32})/resume', path):
                job = self.job_path(match[1])
                if read_json(job / 'job.json')['status'] == 'completed':
                    raise ValueError('This book is already completed.')
                self.server.launcher(self.server.root, job)
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
            if urlsplit(self.path).path == '/api/openrouter-key' and not isinstance(error, (ValueError, RuntimeError)):
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
