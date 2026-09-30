import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '16_Runtime'))
from providers import model_overrides, list_models, connection_settings
from job_runner import create_job, atomic_json
from llm_client import AthenaLLMClient
from web_ui import AthenaServer


class ModelStub(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def answer(self, value):
        data = json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.answer({'object': 'list', 'data': [{'id': 'local-test-model', 'object': 'model'}]})

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.requests.append((self.path, self.headers.get('Authorization'), data))
        self.answer({'id': 'test', 'object': 'chat.completion', 'created': 0, 'model': 'local-test-model',
                     'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{"decision":"APPROVED"}'}}],
                     'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}})


class LocalUiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for folder in ('config', '06_Services', '08_Memory/schemas', 'ui'):
            shutil.copytree(ROOT / folder, self.root / folder, ignore=shutil.ignore_patterns('ui_settings.json'))
        self.launcher = Mock()
        self.server = AthenaServer(self.root, 0, self.launcher)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, data=None, authenticated=True):
        headers = {'Content-Type': 'application/json'}
        if authenticated:
            headers['X-Athena-Token'] = self.server.token
        req = Request(self.url + path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
        return urlopen(req, timeout=10)

    def test_delete_restore_edit_and_update_resume_settings(self):
        job = create_job(self.root, 'Original idea')
        identifier = job.name
        with self.request(f'/api/jobs/{identifier}/edit', {'kind': 'brief', 'text': 'Revised idea'}):
            pass
        self.assertEqual(json.loads((job / 'job.json').read_text())['concept'], 'Revised idea')
        with self.request(f'/api/jobs/{identifier}/delete', {}):
            pass
        with self.request('/api/jobs') as response:
            self.assertEqual(json.load(response), [])
        with self.request('/api/trash') as response:
            self.assertEqual(json.load(response)[0]['id'], identifier)
        with self.assertRaises(HTTPError):
            self.request(f'/api/jobs/{identifier}/resume', {})
        with self.request(f'/api/jobs/{identifier}/restore', {}):
            pass
        with self.request('/api/settings', {'provider': 'ollama', 'model': 'replacement-model'}):
            pass
        with self.request(f'/api/jobs/{identifier}/resume', {'use_current_settings': True}):
            pass
        import yaml
        config = yaml.safe_load((job / 'config/models.yaml').read_text())
        self.assertEqual(config['default_model'], 'replacement-model')
        self.launcher.assert_called_once()

    def test_running_worker_prevents_library_mutations(self):
        from job_lock import job_lock
        job = create_job(self.root, 'Original idea')
        with job_lock(job):
            for action, data in [('delete', {}), ('edit', {'kind': 'brief', 'text': 'Changed'}), ('resume', {})]:
                with self.assertRaises(HTTPError) as caught:
                    self.request(f'/api/jobs/{job.name}/{action}', data)
                self.assertEqual(caught.exception.code, 400)
        self.assertEqual(json.loads((job / 'job.json').read_text())['concept'], 'Original idea')
        self.launcher.assert_not_called()

    def test_real_sdk_uses_local_endpoint_for_every_role_without_cloud_credentials(self):
        stub = ThreadingHTTPServer(('127.0.0.1', 0), ModelStub)
        thread = threading.Thread(target=stub.serve_forever, daemon=True)
        thread.start()
        endpoint = f'http://127.0.0.1:{stub.server_address[1]}/v1'
        try:
            for provider in ('ollama', 'lmstudio'):
                with self.subTest(provider=provider), patch.dict(os.environ, {'OPENROUTER_API_KEY': 'must-never-reach-local-server'}, clear=True):
                    self.assertEqual(list_models(provider, endpoint), ['local-test-model'])
                    job = create_job(self.root, 'Local book', model_config=model_overrides(provider, 'local-test-model', endpoint))
                    client = AthenaLLMClient(str(job / 'config/models.yaml'))
                    try:
                        for role in ('SRV-002', 'SRV-005', 'SRV-030'):
                            self.assertEqual(client.get_model_name(role), 'local-test-model')
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(json.loads(client.execute_prompt('SRV-005', 'Write', 'A story'))['decision'], 'APPROVED')
                        path, auth, body = ModelStub.requests[-1]
                        self.assertEqual(path, '/v1/chat/completions')
                        self.assertNotIn('must-never', auth)
                        self.assertEqual(body['model'], 'local-test-model')
                    finally:
                        client.client.close()
        finally:
            stub.shutdown()
            stub.server_close()
            thread.join()

    def test_ui_create_status_resume_and_manuscript_download(self):
        payload = {'concept': 'A sea of stars', 'provider': 'ollama', 'model': 'local-test-model', 'chapters': 3}
        with self.request('/api/jobs', payload) as response:
            self.assertEqual(response.status, 201)
            identifier = json.load(response)['id']
        self.launcher.assert_called_once()
        with self.request('/api/jobs') as response:
            jobs = json.load(response)
            self.assertEqual(jobs[0]['provider'], 'ollama')
            self.assertEqual(jobs[0]['model'], 'local-test-model')
        with self.request(f'/api/jobs/{identifier}/resume', {}):
            pass
        self.assertEqual(self.launcher.call_count, 2)
        job = self.root / 'jobs' / identifier
        state = json.loads((job / 'job.json').read_text())
        state['status'] = 'completed'
        atomic_json(job / 'job.json', state)
        (job / '08_Memory/manuscript.md').write_text('# Stars\n\n<script>untrusted prose</script>', encoding='utf-8')
        with self.request(f'/api/jobs/{identifier}/manuscript') as response:
            self.assertIn('text/plain', response.headers['Content-Type'])
            self.assertIn('attachment', response.headers['Content-Disposition'])
            self.assertIn(b'untrusted prose', response.read())

    def test_inspect_reports_stages_outline_and_request_budget(self):
        job = create_job(self.root, 'A lighthouse that remembers')
        memory = job / '08_Memory'
        (memory / 'outline.json').write_text(json.dumps({
            'title': 'The Keeper',
            'beat_sheets': [{'act': 1, 'name': 'Arrival', 'beats': [
                {'beat_id': 1, 'goal': 'Meet the keeper', 'conflict': 'A storm', 'outcome': 'He stays'},
                {'beat_id': 2, 'goal': 'Read the first letter', 'conflict': 'Doubt', 'outcome': 'He believes'}]}]}),
            encoding='utf-8')
        (memory / 'pipeline_state.json').write_text(
            json.dumps({'total_chapters': 2, 'last_completed_chapter': 0}), encoding='utf-8')
        state = json.loads((job / 'job.json').read_text())
        state.update(completed_steps=['intake', 'architecture'], active_step='chapter_1', status='running')
        atomic_json(job / 'job.json', state)

        with self.request(f'/api/jobs/{job.name}/inspect') as response:
            detail = json.load(response)
        status = {stage['step']: stage['status'] for stage in detail['stages']}
        self.assertEqual(status['intake'], 'done')
        self.assertEqual(status['characters'], 'pending')
        self.assertEqual(status['chapter_1'], 'active')
        self.assertEqual(status['canon_1'], 'pending')
        self.assertNotIn('chapter_3', status)
        self.assertEqual(detail['total_chapters'], 2)
        self.assertEqual(detail['outline']['title'], 'The Keeper')
        beats = detail['outline']['acts'][0]['beats']
        self.assertEqual([beat['goal'] for beat in beats], ['Meet the keeper', 'Read the first letter'])
        self.assertEqual([beat['status'] for beat in beats], ['active', 'pending'])
        # The draft request is measured from the files this job actually has.
        self.assertIn('Outline', {row['label'] for row in detail['context']['rows']})
        self.assertIn('SRV-005 system prompt', {row['label'] for row in detail['context']['rows']})
        self.assertEqual(detail['context']['context_needed'],
                         detail['context']['prompt_tokens'] + detail['context']['output_tokens'])
        self.assertEqual(detail['budget']['calls'], 0)

    def test_artifact_endpoint_reads_one_file_and_refuses_traversal(self):
        from pipeline_inspect import artifact_text
        job = create_job(self.root, 'A book with artifacts')
        (job / '08_Memory/voice_sample.md').write_text('a voice sample', encoding='utf-8')
        (job / '08_Memory/chapters').mkdir()
        (job / '08_Memory/chapters/chapter_01_summary.json').write_text('{"chapter": 1}', encoding='utf-8')
        with self.request(f'/api/jobs/{job.name}/artifact/voice_sample.md') as response:
            self.assertIn('text/plain', response.headers['Content-Type'])
            self.assertEqual(response.read().decode(), 'a voice sample')
        # Summaries live one level down; the UI URL-encodes them.
        with self.request(f'/api/jobs/{job.name}/artifact/chapters%2Fchapter_01_summary.json') as response:
            self.assertEqual(response.read().decode(), '{"chapter": 1}')
        for name in ('..', '../job.json', 'a/b', '.hidden', '', 'chapters/../job.json'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                artifact_text(job, name)
        for name in ('%2e%2e%2fjob.json', 'missing.json'):
            with self.subTest(name=name):
                with self.assertRaises(HTTPError) as caught:
                    self.request(f'/api/jobs/{job.name}/artifact/{name}')
                self.assertEqual(caught.exception.code, 400)
                caught.exception.close()

    def test_browser_requests_require_session_token(self):
        with self.assertRaises(HTTPError) as caught:
            self.request('/api/jobs', {'concept': 'Cross site'}, authenticated=False)
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()
        self.launcher.assert_not_called()

    def test_invalid_input_does_not_create_job_or_launch_worker(self):
        for chapters in (0, -1, '3', True):
            with self.assertRaises(HTTPError) as caught:
                self.request('/api/jobs', {'concept': 'Story', 'provider': 'ollama', 'model': 'local', 'chapters': chapters})
            self.assertEqual(caught.exception.code, 400)
            caught.exception.close()
        self.launcher.assert_not_called()
        self.assertFalse((self.root / 'jobs').exists())

    def test_local_url_cannot_silently_route_to_cloud(self):
        for endpoint in ('https://example.com/v1', 'http://localhost:1234/api', 'http://user:password@localhost:1234/v1'):
            with self.assertRaises(ValueError):
                connection_settings('lmstudio', endpoint)

    def test_ui_assets_and_bootstrap_are_served(self):
        for path in ('/', '/settings', '/books/' + 'a' * 32, '/app.js', '/style.css', '/settings.css', '/chat.css'):
            with self.request(path) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.read())
        with self.request('/api/bootstrap') as response:
            self.assertEqual(json.load(response)['token'], self.server.token)

    def test_book_messages_endpoint_returns_history_without_starting_worker(self):
        job = create_job(self.root, 'A quiet mystery', 4)
        history = [{'id': 'a', 'role': 'assistant', 'text': 'An idea to discuss.'}]
        with patch('web_ui.reply_to_book', return_value=history) as reply:
            with self.request(f'/api/jobs/{job.name}/messages', {'message': 'What about the setting?'}) as response:
                self.assertEqual(json.load(response)['conversation'], history)
            reply.assert_called_once_with(job.resolve(), 'What about the setting?')
        self.launcher.assert_not_called()

    def test_saved_settings_apply_to_new_jobs_and_preserve_existing_jobs(self):
        settings = {'provider': 'ollama', 'model': 'local-a', 'max_calls_per_job': 75,
                    'max_output_tokens': 4096, 'timeout_seconds': 1200}
        with self.request('/api/settings', settings) as response:
            self.assertEqual(json.load(response)['model'], 'local-a')
        with self.request('/api/jobs', {'concept': 'A story'}) as response:
            identifier = json.load(response)['id']
        import yaml
        config_file = self.root / 'jobs' / identifier / 'config/models.yaml'
        config = yaml.safe_load(config_file.read_text())
        self.assertEqual(config['default_model'], 'local-a')
        self.assertEqual(config['max_calls_per_job'], 75)
        self.assertEqual(config['max_output_tokens'], 4096)
        self.assertEqual(config['connection']['timeout_seconds'], 1200)
        settings['model'] = 'local-b'
        with self.request('/api/settings', settings):
            pass
        with self.request('/api/settings') as response:
            self.assertEqual(json.load(response)['model'], 'local-b')
        self.assertEqual(yaml.safe_load(config_file.read_text())['default_model'], 'local-a')
        self.assertEqual(json.loads((self.root / 'config/ui_settings.json').read_text())['model'], 'local-b')

    def test_invalid_settings_are_not_saved(self):
        for value in (0, True, 2.5):
            with self.assertRaises(HTTPError) as caught:
                self.request('/api/settings', {'provider': 'ollama', 'model': 'local', 'max_calls_per_job': value})
            self.assertEqual(caught.exception.code, 400)
            caught.exception.close()
        self.assertFalse((self.root / 'config/ui_settings.json').exists())

    def test_key_save_status_and_delete_never_return_or_snapshot_secret(self):
        vault = {}
        secret = 'dummy-key-for-ui-test-only'
        with patch('credentials.read_key', side_effect=lambda root=None: vault.get('key')), \
             patch('credentials.save_key', side_effect=lambda key, root=None: vault.update(key=key)), \
             patch('credentials.delete_key', side_effect=lambda root=None: vault.clear()), \
             patch('providers.legacy_openrouter_key', return_value=(None, None)):
            with self.request('/api/openrouter-key', {'action': 'save', 'key': secret}) as response:
                content = response.read().decode()
                self.assertNotIn(secret, content)
                self.assertTrue(json.loads(content)['saved'])
            with self.request('/api/openrouter-key') as response:
                self.assertNotIn(secret, response.read().decode())
            with self.request('/api/settings', {'provider': 'openrouter', 'model': 'example/model'}) as response:
                self.assertNotIn(secret, response.read().decode())
            with self.request('/api/jobs', {'concept': 'A story'}) as response:
                identifier = json.load(response)['id']
            for path in (self.root / 'jobs' / identifier / 'config').rglob('*'):
                if path.is_file():
                    self.assertNotIn(secret, path.read_text(encoding='utf-8'))
            with self.request('/api/openrouter-key', {'action': 'remove'}) as response:
                self.assertFalse(json.load(response)['configured'])
            self.assertFalse(vault)

    def test_cloud_provider_key_endpoints_and_local_protection(self):
        vault = {}
        secret = 'dummy-key-for-provider-test-123'
        def fake_read(root=None, provider='openrouter'):
            return vault.get(provider)
        def fake_save(key, root=None, provider='openrouter'):
            vault[provider] = key
        def fake_delete(root=None, provider='openrouter'):
            vault.pop(provider, None)

        with patch('credentials.read_key', side_effect=fake_read), \
             patch('credentials.save_key', side_effect=fake_save), \
             patch('credentials.delete_key', side_effect=fake_delete), \
             patch('providers.legacy_provider_key', return_value=(None, None)):
            for provider in ('openrouter', 'openai', 'google', 'groq'):
                with self.subTest(provider=provider):
                    # Save
                    with self.request('/api/provider-key', {'provider': provider, 'action': 'save', 'key': secret}) as response:
                        content = response.read().decode()
                        self.assertNotIn(secret, content)
                        self.assertTrue(json.loads(content)['saved'])
                    self.assertEqual(vault.get(provider), secret)

                    # Status
                    with self.request('/api/provider-key', {'provider': provider, 'action': 'status'}) as response:
                        content = response.read().decode()
                        self.assertNotIn(secret, content)
                        self.assertTrue(json.loads(content)['configured'])

                    # Remove
                    with self.request('/api/provider-key', {'provider': provider, 'action': 'remove'}) as response:
                        self.assertFalse(json.load(response)['configured'])
                    self.assertNotIn(provider, vault)

            # Local providers must be rejected for cloud API key management
            for local_provider in ('ollama', 'lmstudio'):
                with self.subTest(local_provider=local_provider):
                    with self.assertRaises(HTTPError) as caught:
                        self.request('/api/provider-key', {'provider': local_provider, 'action': 'status'})
                    self.assertEqual(caught.exception.code, 400)
                    caught.exception.close()


if __name__ == '__main__':
    unittest.main()
