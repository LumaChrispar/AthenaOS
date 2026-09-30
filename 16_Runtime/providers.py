"""Connection settings shared by the worker, CLI, and local UI."""
import os
import json
from pathlib import Path
from urllib.parse import urlsplit
import credentials

ENDPOINTS = {
    'openrouter': 'https://openrouter.ai/api/v1',
    'openai': 'https://api.openai.com/v1',
    'google': 'https://generativelanguage.googleapis.com/v1beta/openai',
    'groq': 'https://api.groq.com/openai/v1',
    'lmstudio': 'http://127.0.0.1:1234/v1',
    'ollama': 'http://127.0.0.1:11434/v1',
}
CLOUD_PROVIDERS = ('openrouter', 'openai', 'google', 'groq')
ENV_KEYS = {'openrouter': 'OPENROUTER_API_KEY', 'openai': 'OPENAI_API_KEY',
            'google': 'GEMINI_API_KEY', 'groq': 'GROQ_API_KEY'}
PROVIDER_NAMES = {'openrouter': 'OpenRouter', 'openai': 'OpenAI', 'google': 'Google Gemini', 'groq': 'Groq'}

MODEL_GROUPS = {
    'architecture-reasoning': ['SRV-001', 'SRV-002', 'SRV-007', 'SRV-010', 'SRV-016'],
    'character-world-building': ['SRV-003', 'SRV-004', 'SRV-011', 'SRV-012', 'SRV-015'],
    'prose-generation': ['SRV-005', 'SRV-006', 'SRV-008', 'SRV-013'],
    'voice-variation': ['SRV-027', 'SRV-028'],
    'analysis-critique': ['SRV-009', 'SRV-014', 'SRV-019', 'SRV-022', 'SRV-023', 'SRV-026'],
}


def connection_settings(provider='openrouter', base_url=None):
    if provider not in ENDPOINTS:
        raise ValueError('Choose OpenRouter, OpenAI, Google Gemini, Groq, LM Studio, or Ollama.')
    url = (base_url or ENDPOINTS[provider]).rstrip('/')
    parsed = urlsplit(url)
    if provider in CLOUD_PROVIDERS:
        if url != ENDPOINTS[provider]:
            raise ValueError(f'{PROVIDER_NAMES[provider]} must use its official API endpoint.')
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


def legacy_provider_key(provider):
    variable = ENV_KEYS.get(provider)
    key = os.environ.get(variable) if variable else None
    if key:
        return key, 'environment'
    if provider == 'openrouter':
        return legacy_openrouter_key()
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


def provider_key_status(provider, root=None):
    if provider not in CLOUD_PROVIDERS:
        return {'configured': False, 'saved': False, 'source': None, 'storage_error': None}
    try:
        saved = credentials.read_key(root, provider)
        storage_error = None
    except TypeError:  # compatibility with callers that wrap the original one-argument vault method
        saved = credentials.read_key(root)
        storage_error = None
    except Exception:
        saved = None
        storage_error = 'Secure storage is unavailable in this session.'
    if saved:
        return {'configured': True, 'saved': True, 'source': 'saved', 'storage_error': None}
    key, source = legacy_provider_key(provider)
    return {'configured': bool(key), 'saved': False, 'source': source, 'storage_error': storage_error}


def api_key_for(provider, root=None):
    # Never read or forward cloud credentials for a local provider.
    if provider not in CLOUD_PROVIDERS:
        return os.environ.get('LM_STUDIO_API_KEY', 'local-model') if provider == 'lmstudio' else 'ollama'
    key = None
    try:
        key = credentials.read_key(root, provider)
    except TypeError:  # keep compatibility with extensions wrapping the original vault helper
        key = credentials.read_key(root)
    except Exception:
        pass  # Existing environment-based setups work without a desktop vault.
    if not key:
        key, _ = legacy_provider_key(provider)
    if not key:
        raise ValueError(f'Add your {PROVIDER_NAMES.get(provider, provider)} API key in Settings, or set {ENV_KEYS.get(provider, "the provider API key environment variable")}.')
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


def model_info(provider, model, base_url=None, root=None):
    """Return public capability metadata for one model, when its server exposes it."""
    import httpx
    settings = connection_settings(provider, base_url)
    if not isinstance(model, str) or not model.strip():
        raise ValueError('Choose a model first.')
    try:
        response = httpx.get(settings['base_url'] + '/models',
                             headers={'Authorization': 'Bearer ' + api_key_for(provider, root)},
                             timeout=10, follow_redirects=False)
        response.raise_for_status()
        rows = response.json().get('data', [])
        record = next((row for row in rows if row.get('id') == model.strip()), None)
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return {'model': model.strip(), 'available': False, 'context_length': None,
                'max_output_tokens': None}
    if not record:
        return {'model': model.strip(), 'available': False, 'context_length': None,
                'max_output_tokens': None}
    context = record.get('context_length') or record.get('context_window')
    output = record.get('max_completion_tokens') or (record.get('top_provider') or {}).get('max_completion_tokens')
    return {'model': model.strip(), 'available': True,
            'context_length': context if type(context) is int and context > 0 else None,
            'max_output_tokens': output if type(output) is int and output > 0 else None}


def list_model_catalog(provider, base_url=None, root=None):
    """List selectable models and their advertised capability metadata."""
    import httpx
    settings = connection_settings(provider, base_url)
    api_key = api_key_for(provider, root)
    try:
        response = httpx.get(settings['base_url'] + '/models',
                             headers={'Authorization': 'Bearer ' + api_key},
                             timeout=10, follow_redirects=False)
        response.raise_for_status()
        records = response.json().get('data', [])
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise ValueError('Could not read the model list. Check the provider connection and try again.') from None
    observed = {}
    jobs = Path(root or Path(__file__).resolve().parents[1]) / 'jobs'
    if jobs.is_dir():
        for config_path in jobs.glob('*/config/models.yaml'):
            try:
                import yaml
                config = yaml.safe_load(config_path.read_text(encoding='utf-8')) or {}
                connection = config.get('connection', {})
                if connection.get('provider') != settings['provider'] or (base_url and connection.get('base_url', '').rstrip('/') != settings['base_url']):
                    continue
                usage_path = config_path.parent.parent / '08_Memory' / 'usage.json'
                usage = json.loads(usage_path.read_text(encoding='utf-8')) if usage_path.exists() else {}
                for model_id, stats in (usage.get('by_model') or {}).items():
                    current = observed.setdefault(model_id, {'calls': 0, 'completion_tokens': 0, 'response_seconds': 0.0})
                    for key in current:
                        current[key] += stats.get(key, 0)
            except (OSError, ValueError, TypeError):
                continue
    catalog = []
    for row in records:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str):
            continue
        top = row.get('top_provider') or {}
        context = row.get('context_length') or row.get('context_window')
        output = row.get('max_completion_tokens') or top.get('max_completion_tokens')
        pricing = row.get('pricing') if isinstance(row.get('pricing'), dict) else {}
        free = settings['provider'] not in CLOUD_PROVIDERS or row['id'].endswith(':free')
        if settings['provider'] in CLOUD_PROVIDERS and pricing:
            try:
                free = float(pricing.get('prompt', 1)) == 0 and float(pricing.get('completion', 1)) == 0
            except (TypeError, ValueError):
                pass
        catalog.append({
            'id': row['id'], 'name': row.get('name') or row['id'],
            'description': row.get('description') or '',
            'context_length': context if type(context) is int and context > 0 else None,
            'max_output_tokens': output if type(output) is int and output > 0 else None,
            'pricing': pricing, 'free': free,
            'observed': observed.get(row['id'], {}),
        })
    return sorted(catalog, key=lambda item: item['id'].casefold())


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


def test_provider_key(provider, key=None, root=None):
    if provider == 'openrouter':
        return test_openrouter_key(key, root)
    if provider not in CLOUD_PROVIDERS:
        raise ValueError('Choose a cloud provider to test its API key.')
    import httpx
    key = credentials.validate_key(key) if key else api_key_for(provider, root)
    endpoint = connection_settings(provider)['base_url'] + '/models'
    try:
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            response = client.get(endpoint, headers={'Authorization': 'Bearer ' + key})
    except httpx.RequestError:
        raise ValueError(f'Could not reach {PROVIDER_NAMES[provider]}. Check the connection and try again.') from None
    if response.status_code in (401, 403):
        raise ValueError(f'{PROVIDER_NAMES[provider]} did not accept this key. Check that it is valid for this provider.')
    if response.status_code != 200:
        raise ValueError(f'{PROVIDER_NAMES[provider]} could not verify the key (HTTP {response.status_code}). Try again later.')
    return {'valid': True, 'message': f'{PROVIDER_NAMES[provider]} key verified. No text was generated.'}
