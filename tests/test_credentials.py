import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '16_Runtime'))
import credentials
import providers


class CredentialTests(unittest.TestCase):
    def test_saved_key_overrides_legacy_and_local_providers_never_read_it(self):
        with patch('credentials.read_key', return_value='saved-test-secret') as read, patch('providers.legacy_openrouter_key', return_value=('environment-secret', 'environment')):
            self.assertEqual(providers.api_key_for('openrouter'), 'saved-test-secret')
            read.reset_mock()
            self.assertEqual(providers.api_key_for('ollama'), 'ollama')
            read.assert_not_called()

    def test_status_contains_no_secret_and_removal_can_fall_back_to_environment(self):
        with patch('credentials.read_key', return_value='saved-test-secret'), patch('providers.legacy_openrouter_key', return_value=('environment-secret', 'environment')):
            status = providers.openrouter_key_status()
            self.assertTrue(status['saved'])
            self.assertNotIn('secret', json.dumps(status))
        with patch('credentials.read_key', return_value=None), patch('providers.legacy_openrouter_key', return_value=('environment-secret', 'environment')):
            self.assertEqual(providers.openrouter_key_status()['source'], 'environment')

    def test_key_test_calls_only_authenticated_metadata_endpoint(self):
        with patch('httpx.Client') as factory:
            client = factory.return_value.__enter__.return_value
            client.get.return_value.status_code = 200
            self.assertTrue(providers.test_openrouter_key('dummy-key-for-mocked-test')['valid'])
            client.get.assert_called_once_with('https://openrouter.ai/api/v1/key', headers={'Authorization': 'Bearer dummy-key-for-mocked-test'})
            factory.assert_called_once_with(timeout=10, follow_redirects=False)
            client.post.assert_not_called()

    def test_invalid_key_error_does_not_echo_provider_body_or_secret(self):
        with patch('httpx.Client') as factory:
            client = factory.return_value.__enter__.return_value
            client.get.return_value.status_code = 401
            client.get.return_value.text = 'dummy-key-for-mocked-test'
            with self.assertRaises(ValueError) as caught:
                providers.test_openrouter_key('dummy-key-for-mocked-test')
            self.assertNotIn('dummy-key', str(caught.exception))

    def test_control_characters_and_empty_keys_are_rejected(self):
        for key in ('', 'short', 'a' * 20 + '\x00', 'a' * 20 + '\ninside'):
            with self.assertRaises(ValueError):
                credentials.validate_key(key)
