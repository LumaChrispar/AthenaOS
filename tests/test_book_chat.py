import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '16_Runtime'))
from book_chat import reply_to_book, read_messages, progress_messages


class BookChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.job = Path(self.temp.name)
        (self.job / '08_Memory').mkdir()
        self.state = {'concept': 'The witches create prophecies.', 'status': 'running', 'active_step': 'architecture', 'completed_steps': ['intake']}
        (self.job / 'job.json').write_text(json.dumps(self.state))
        self.client = Mock(max_calls=200, max_output_tokens=8192)
        self.client.execute_prompt.return_value = 'The witches can be a source of conflict.'

    def tearDown(self):
        self.temp.cleanup()

    def test_chat_is_persisted_and_does_not_change_worker_state(self):
        original = (self.job / 'job.json').read_bytes()
        reply_to_book(self.job, 'What motivates the witches?', lambda _: self.client)
        history = read_messages(self.job)
        self.assertEqual([message['role'] for message in history], ['user', 'assistant'])
        self.assertEqual(history[-1]['text'], self.client.execute_prompt.return_value)
        self.assertEqual((self.job / 'job.json').read_bytes(), original)
        self.assertEqual(self.client.max_calls, 50)
        self.assertEqual(self.client.max_output_tokens, 2048)
        self.assertTrue(self.client.usage_path.endswith('chat_usage.json'))
        self.assertIn('read-only discussion', self.client.execute_prompt.call_args.args[1])
        self.assertIn(self.state['concept'], self.client.execute_prompt.call_args.args[2])

    def test_failed_model_reply_is_visible_without_losing_user_message(self):
        self.client.execute_prompt.side_effect = RuntimeError('private diagnostic')
        history = reply_to_book(self.job, 'How is the book going?', lambda _: self.client)
        self.assertEqual(history[0]['role'], 'user')
        self.assertEqual(history[1]['role'], 'error')
        self.assertNotIn('private diagnostic', json.dumps(history))
        self.assertEqual(json.loads((self.job / 'job.json').read_text()), self.state)

    def test_invalid_message_does_not_call_model_or_write_history(self):
        for message in (' ', 'a' * 8001, None):
            with self.assertRaises(ValueError):
                reply_to_book(self.job, message, lambda _: self.client)
        self.client.execute_prompt.assert_not_called()
        self.assertEqual(read_messages(self.job), [])

    def test_progress_uses_actual_logs_and_reports_failure_without_claiming_completion(self):
        state = {**self.state, 'status': 'failed', 'error': 'Connection error.'}
        updates = progress_messages(state, '--- PHASE 1: STORY ARCHITECTURE (SRV-002) ---\nSaved artifact to private/path\n')
        text = json.dumps(updates)
        self.assertIn('Story architecture'.lower(), text.lower())
        self.assertIn('Connection error.', text)
        self.assertNotIn('private/path', text)
        self.assertNotIn('manuscript is ready', text)
