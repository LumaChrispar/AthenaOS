import asyncio
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '16_Runtime'))
import audiobook
from job_runner import create_job, atomic_json
from job_lock import job_lock
from llm_client import ResponseLimitError
from orchestrator import Orchestrator
from web_ui import AthenaServer


def wav(rate=24000, frames=2400):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b'\0\0' * frames)
    return buffer.getvalue()


class AudiobookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for folder in ('config', '06_Services', '08_Memory/schemas', 'ui'):
            shutil.copytree(ROOT / folder, self.root / folder)
        self.job = create_job(self.root, 'A finished mystery', 2)
        self.memory = self.job / '08_Memory'
        atomic_json(self.memory / 'metadata.json', {'title': 'The Door', 'blurb': 'A mystery by the sea.'})
        atomic_json(self.memory / 'pipeline_state.json', {'total_chapters': 2, 'last_completed_chapter': 2})
        atomic_json(self.memory / 'chapter_01.json', {'title': 'Arrival', 'prose_content': 'She heard the sea. ' * 180})
        atomic_json(self.memory / 'chapter_02.json', {'title': 'Return', 'prose_content': 'At dawn she returned.'})
        (self.memory / 'manuscript.md').write_text('# The Door\nFinal manuscript.', encoding='utf-8')
        state = audiobook.read(self.job / 'job.json')
        state.update(status='completed', completed_steps=['chapter_1', 'chapter_2'])
        atomic_json(self.job / 'job.json', state)

    def tearDown(self):
        self.temp.cleanup()

    def test_full_book_master_survives_reload_and_no_repeat_on_resume(self):
        generate = Mock(return_value=wav())
        audiobook.prepare(self.job, audiobook.DEFAULTS, [1, 2])
        audiobook.run(self.job, generate)
        state = audiobook.status(self.job)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(len(state['tracks']), 2)
        with wave.open(str(self.job / 'audio' / state['master']['filename'])) as audio:
            self.assertEqual(audio.getnframes(), generate.call_count * 2400)
        calls = generate.call_count
        audiobook.prepare(self.job, audiobook.DEFAULTS, [1, 2])
        audiobook.run(self.job, generate)
        self.assertEqual(generate.call_count, calls)

    def test_failed_chunk_resumes_without_losing_preceding_audio(self):
        generate = Mock(side_effect=[wav(), RuntimeError('Interrupted')])
        audiobook.prepare(self.job, audiobook.DEFAULTS, [1])
        with self.assertRaisesRegex(RuntimeError, 'Interrupted'):
            audiobook.run(self.job, generate)
        state = audiobook.status(self.job)
        self.assertEqual(state['status'], 'failed')
        self.assertEqual(state['completed_chunks'], 1)
        generate = Mock(return_value=wav())
        total = state['total_chunks']
        audiobook.prepare(self.job, audiobook.DEFAULTS, [1])
        audiobook.run(self.job, generate)
        self.assertEqual(generate.call_count, total - 1)
        self.assertIn('1', audiobook.status(self.job)['tracks'])

    def test_manuscript_edits_and_voice_changes_invalidate_audio(self):
        generate = Mock(return_value=wav())
        audiobook.prepare(self.job, audiobook.DEFAULTS, [1, 2])
        audiobook.run(self.job, generate)
        chapter = audiobook.read(self.memory / 'chapter_01.json')
        chapter['prose_content'] = 'A revised arrival.'
        atomic_json(self.memory / 'chapter_01.json', chapter)
        state = audiobook.status(self.job)
        self.assertNotIn('1', state['tracks'])
        self.assertIn('2', state['tracks'])
        self.assertNotIn('master', state)
        audiobook.prepare(self.job, {**audiobook.DEFAULTS, 'voice': 'af_bella'}, [2])
        self.assertEqual(audiobook.status(self.job)['tracks'], {})

    def test_chunk_boundaries_and_real_riff_headers(self):
        text = 'x' * 4000 + ' End.\n\nNext paragraph.'
        parts = audiobook.chunks(text)
        self.assertTrue(all(0 < len(part) <= 1400 for part in parts))
        self.assertEqual(''.join(parts).replace(' ', '').replace('\n', ''), text.replace(' ', '').replace('\n', ''))
        value = bytearray(wav())
        value[4:8] = b'\xff' * 4
        value[40:44] = b'\xff' * 4
        spec, pcm = audiobook.wav_data(bytes(value))
        self.assertEqual(spec, (1, 2, 24000))
        self.assertEqual(len(pcm), 4800)
        with self.assertRaises(ValueError):
            audiobook.wav_data(b'not audio')

    def test_mismatched_audio_is_never_exported(self):
        a, b, output = self.root / 'a.wav', self.root / 'b.wav', self.root / 'out.wav'
        a.write_bytes(wav()); b.write_bytes(wav(16000))
        with self.assertRaisesRegex(ValueError, 'formats changed'):
            audiobook.merge_wavs([a, b], output)
        self.assertFalse(output.exists())

    def test_speech_contract_and_no_cloud_credentials_for_local(self):
        response = Mock(content=wav())
        with patch('audiobook.httpx.post', return_value=response) as post, patch('audiobook.api_key_for') as key:
            audiobook.speech('A line of prose.', audiobook.DEFAULTS, self.root)
        key.assert_not_called()
        self.assertEqual(post.call_args.args[0], 'http://127.0.0.1:8880/v1/audio/speech')
        self.assertEqual(post.call_args.kwargs['json']['input'], 'A line of prose.')
        self.assertEqual(post.call_args.kwargs['json']['response_format'], 'wav')

    def test_settings_cannot_silently_send_local_text_to_cloud(self):
        for url in ('https://example.com/v1', 'http://user:pass@localhost:8880/v1', 'http://localhost:8880/v1?key=abc'):
            with self.assertRaises(ValueError):
                audiobook.validate_settings({**audiobook.DEFAULTS, 'base_url': url})
        for speed in (True, 0, float('nan')):
            with self.assertRaises(ValueError):
                audiobook.validate_settings({**audiobook.DEFAULTS, 'speed': speed})

    def test_worker_lock_and_pending_recovery(self):
        audiobook.prepare(self.job, audiobook.DEFAULTS, [1])
        with job_lock(self.job / 'audio'):
            with self.assertRaises(RuntimeError):
                audiobook.prepare(self.job, audiobook.DEFAULTS, [1])
        state = audiobook.read(self.job / 'audio/state.json')
        state['updated_at'] = 0
        atomic_json(self.job / 'audio/state.json', state)
        self.assertEqual(audiobook.status(self.job)['status'], 'interrupted')

    def test_http_studio_audio_ranges_auth_and_stale_track_rejection(self):
        audiobook.prepare(self.job, audiobook.DEFAULTS, [1, 2])
        audiobook.run(self.job, lambda text, settings: wav())
        launcher = Mock()
        server = AthenaServer(self.root, 0, audio_launcher=launcher)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_address[1]}'
        try:
            for path in (f'/books/{self.job.name}/studio', '/studio.js', '/studio.css', f'/api/jobs/{self.job.name}/studio'):
                with urlopen(url + path) as response:
                    self.assertEqual(response.status, 200)
            track = audiobook.status(self.job)['tracks']['1']['filename']
            path = f'/api/jobs/{self.job.name}/audio/{track}'
            with urlopen(Request(url + path, headers={'Range': 'bytes=0-43'})) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(len(response.read()), 44)
            data = json.dumps({'settings': audiobook.DEFAULTS, 'chapters': [2]}).encode()
            with self.assertRaises(HTTPError) as caught:
                urlopen(Request(url + f'/api/jobs/{self.job.name}/narrate', data=data))
            self.assertEqual(caught.exception.code, 403)
            caught.exception.close()
            with urlopen(Request(url + f'/api/jobs/{self.job.name}/narrate', data=data, headers={'X-Athena-Token': server.token})) as response:
                self.assertEqual(response.status, 202)
            launcher.assert_called_once()
            chapter = audiobook.read(self.memory / 'chapter_01.json'); chapter['prose_content'] = 'Revised.'
            atomic_json(self.memory / 'chapter_01.json', chapter)
            with self.assertRaises(HTTPError) as caught:
                urlopen(url + path)
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_truncated_character_planning_adapts_and_resumes_profiles(self):
        model = Mock()
        outline = {'title': 'The Door', 'beat_sheets': [{'beats': [{'goal': 'Ada arrives', 'conflict': 'Ben refuses', 'outcome': 'Ada enters'}]}]}
        atomic_json(self.memory / 'outline.json', outline)
        model.execute_prompt.side_effect = [ResponseLimitError('limit'), '{"names": ["Ada", "Ben"]}',
                                            '{"name": "Ada", "psychology": {"want": "Enter"}}', RuntimeError('offline')]
        with patch('orchestrator.AthenaLLMClient', return_value=model), contextlib.redirect_stdout(io.StringIO()):
            orch = Orchestrator(str(self.job))
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                asyncio.run(orch.run_phase_2_psychology())
            model.execute_prompt.reset_mock()
            model.execute_prompt.side_effect = ['{"name": "Ben", "psychology": {"want": "Stay"}}']
            asyncio.run(orch.run_phase_2_psychology())
        self.assertEqual(model.execute_prompt.call_count, 1)
        self.assertEqual([c['name'] for c in audiobook.read(self.memory / 'psychology.json')['characters']], ['Ada', 'Ben'])


if __name__ == '__main__':
    unittest.main()
