"""Connection settings shared by the worker, CLI, and local UI."""
import os
from pathlib import Path
from urllib.parse import urlsplit
import credentials

ENDPOINTS = {
    'openrouter': 'https://openrouter.ai/api/v1',
    'lmstudio': 'http://127.0.0.1:1234/v1',
    'ollama': 'http://127.0.0.1:11434/v1',
}


def connection_settings(provider='openrouter', base_url=None):
    if provider not in ENDPOINTS:
        raise ValueError('Choose openrouter, lmstudio, or ollama.')
    url = (base_url or ENDPOINTS[provider]).rstrip('/')
    parsed = urlsplit(url)
    if provider == 'openrouter':
        if url != ENDPOINTS[provider]:
            raise ValueError('OpenRouter must use its official API endpoint.')
    elif (parsed.scheme not in ('http', 'https') or parsed.hostname not in ('localhost', '127.0.0.1', '::1')
          or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path != '/v1'):
        raise ValueError('Local server URL must use localhost or a loopback address and end in /v1.')
    return {'provider': provider, 'base_url': url}


def legacy_openrouter_key():
    key = os.environ.get('OPENROUTER_API_KEY')
    if key:
        return key, 'environment'
    env_file = Path.home() / '.hermes' / '.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            if line.startswith('OPENROUTER_API_KEY='):
                key = line.split('=', 1)[1].strip().strip('"\'')
                if key:
                    return key, 'Hermes'
    return None, None


def openrouter_key_status(root=None):
    try:
        saved = credentials.read_key(root)
        storage_error = None
    except Exception:
        saved = None
        storage_error = 'Secure storage is unavailable in this session.'
    if saved:
        return {'configured': True, 'saved': True, 'source': 'saved', 'storage_error': None}
    key, source = legacy_openrouter_key()
    return {'configured': bool(key), 'saved': False, 'source': source, 'storage_error': storage_error}


def api_key_for(provider, root=None):
    # Never read or forward cloud credentials for a local provider.
    if provider != 'openrouter':
        return os.environ.get('LM_STUDIO_API_KEY', 'local-model') if provider == 'lmstudio' else 'ollama'
    key = None
    try:
        key = credentials.read_key(root)
    except Exception:
        pass  # Existing environment-based setups work without a desktop vault.
    if not key:
        key, _ = legacy_openrouter_key()
    if not key:
        raise ValueError('Add your OpenRouter API key in Settings, or set OPENROUTER_API_KEY.')
    return key


def model_overrides(provider, model, base_url=None):
    connection = connection_settings(provider, base_url)
    if not isinstance(model, str) or not model.strip():
        raise ValueError('Enter a model ID from your model server.')
    return {'connection': connection, 'default_model': model.strip(), 'use_default_model_for_all_services': True}


def list_models(provider, base_url=None, root=None):
    from openai import OpenAI
    settings = connection_settings(provider, base_url)
    with OpenAI(base_url=settings['base_url'], api_key=api_key_for(provider, root), timeout=10, max_retries=0) as client:
        return sorted(model.id for model in client.models.list().data)


def test_openrouter_key(key=None, root=None):
    import httpx
    key = credentials.validate_key(key) if key else api_key_for('openrouter', root)
    try:
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            response = client.get(ENDPOINTS['openrouter'] + '/key', headers={'Authorization': 'Bearer ' + key})
    except httpx.RequestError:
        raise ValueError('Could not reach OpenRouter. Check your internet connection and try again.') from None
    if response.status_code in (401, 403):
        raise ValueError('OpenRouter did not accept this key. Copy a valid key from your OpenRouter account.')
    if response.status_code != 200:
        raise ValueError(f'OpenRouter could not verify the key (HTTP {response.status_code}). Try again later.')
    return {'valid': True, 'message': 'Key verified. No text was generated.'}
