import os
import yaml
import time
import asyncio
from functools import wraps
from openai import OpenAI, APIConnectionError, APITimeoutError
import json
from job_runner import atomic_json
from providers import connection_settings, api_key_for, CLOUD_PROVIDERS, PROVIDER_NAMES

_MODEL_LIMIT_CACHE = {}


def _model_limits(provider, base_url, api_key, model_name):
    """Read advertised context/output limits when the server exposes them."""
    import httpx

    cache_key = (provider, base_url, model_name)
    if cache_key in _MODEL_LIMIT_CACHE:
        return _MODEL_LIMIT_CACHE[cache_key]
    try:
        response = httpx.get(
            base_url.rstrip('/') + '/models',
            headers={'Authorization': 'Bearer ' + api_key},
            timeout=10,
            follow_redirects=False,
        )
        response.raise_for_status()
        rows = response.json().get('data', [])
        model = next((row for row in rows if row.get('id') == model_name), None)
        if not model:
            return None, None
        context = model.get('context_length') or model.get('context_window')
        maximum = model.get('max_completion_tokens')
        if maximum is None:
            maximum = (model.get('top_provider') or {}).get('max_completion_tokens')
        limits = (context if type(context) is int and context > 0 else None,
                  maximum if type(maximum) is int and maximum > 0 else None)
        _MODEL_LIMIT_CACHE[cache_key] = limits
        return limits
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        # Many local OpenAI-compatible servers omit model metadata. The runtime
        # then uses a conservative fallback instead of preventing a job from starting.
        return None, None


def _estimate_tokens(text):
    # Conservative rough estimate for mixed prose/JSON without a model tokenizer.
    return max(1, (len(text) + 2) // 3)

def with_retry(max_attempts=3, base_delay=2.0):
    """Exponential backoff retry decorator for LLM calls."""
    # 'empty content' is included because providers routinely return a completed-but-blank
    # message (HTTP 200, null content) when an upstream generation hits its own ceiling.
    RETRYABLE_ERRORS = ['timeout', 'rate_limit', 'connection', '429', '503', '502', '504',
                        'empty content']
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_str = str(e).lower()
                    is_retryable = any(err in error_str for err in RETRYABLE_ERRORS)
                    
                    if not is_retryable or attempt == max_attempts - 1:
                        raise
                    
                    delay = base_delay * (2 ** attempt)
                    print(f"[RETRY {attempt+1}/{max_attempts}] {e}. Waiting {delay}s...")
                    time.sleep(delay)
        return wrapper
    return decorator


class AthenaLLMClient:
    def __init__(self, config_path: str):
        # Load model routing config
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        connection = self.config.get('connection', {})
        settings = connection_settings(connection.get('provider', 'openrouter'), connection.get('base_url'))
        self.provider = settings['provider']
        self.base_url = settings['base_url']
        api_key = api_key_for(self.provider)
        self.api_key = api_key
        
        self.client = OpenAI(
            base_url=settings['base_url'],
            api_key=api_key,
            timeout=connection.get('timeout_seconds', 300 if self.provider in CLOUD_PROVIDERS else 900),
            max_retries=0,
        )
        self.usage_path = os.path.join(os.path.dirname(config_path), '..', '08_Memory', 'usage.json')
        self.max_calls = self.config.get('max_calls_per_job', 200)
        self.max_output_tokens = self.config.get('max_output_tokens', 8192)
        self.fallback_context_tokens = self.config.get('fallback_context_tokens', 32768)
        self.model_limits = {}
        self.role_models = self.config.get('role_models', {})
        
        # Build capability -> model mapping from models.yaml
        self.capability_model = {}
        for model_def in self.config.get("models", []):
            for cap in model_def.get("capabilities", []):
                self.capability_model[cap] = model_def
        
        self.default_temp = self.config.get("default_temperature", 0.5)
        self.default_model = self.config.get("default_model", "nvidia/nemotron-3-ultra-550b-a55b:free")
        self.use_default_model = self.provider not in CLOUD_PROVIDERS or self.config.get('use_default_model_for_all_services', False)

    def get_model_for_service(self, service_id: str) -> dict:
        """Get the model configuration for a service ID."""
        config = dict(self.capability_model.get(service_id, {
            "model": self.default_model,
            "temperature": self.default_temp
        }))
        group_id = config.get('id')
        role_models = getattr(self, 'role_models', {})
        if group_id in role_models and role_models[group_id]:
            config['model'] = role_models[group_id]
        if getattr(self, 'use_default_model', False):
            config['model'] = self.default_model
        return config

    def get_temperature(self, service_id: str) -> float:
        """Get temperature for a service ID."""
        model_config = self.get_model_for_service(service_id)
        return model_config.get("temperature", self.default_temp)

    def get_model_name(self, service_id: str) -> str:
        """Get model name for a service ID."""
        model_config = self.get_model_for_service(service_id)
        return model_config.get("model", self.default_model)

    @with_retry(max_attempts=3, base_delay=2.0)
    def execute_prompt(self, service_id: str, system_prompt: str, user_prompt: str) -> str:
        """Routes the prompt to the configured server with bounded retries."""
        model_config = self.get_model_for_service(service_id)
        model_name = model_config.get("model", self.default_model)
        temperature = model_config.get("temperature", self.default_temp)

        if not hasattr(self, 'model_limits'):
            self.model_limits = {}
        if model_name not in self.model_limits:
            self.model_limits[model_name] = _model_limits(
                getattr(self, 'provider', None), getattr(self, 'base_url', None), getattr(self, 'api_key', None), model_name)
        context_limit, model_output_limit = self.model_limits[model_name]
        context_limit = context_limit or getattr(self, 'fallback_context_tokens', 32768)
        output_limit = min(self.max_output_tokens,
                           model_output_limit or min(self.max_output_tokens, 8192))
        prompt_tokens = _estimate_tokens(system_prompt) + _estimate_tokens(user_prompt)
        # Keep a 10% context reserve (at least 512 tokens) for tokenizer variance
        # and provider-side message framing.
        available = context_limit - prompt_tokens - max(512, context_limit // 10)
        request_output_tokens = min(output_limit, max(256, available))
        
        print(f"[{service_id}] Sending task (model: {model_name}, temp: {temperature})...")
        print(f"[{service_id}] Request budget: prompt≈{prompt_tokens} tokens; output≤{request_output_tokens}; context={context_limit}.")
        
        try:
            usage = {'calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0}
            if os.path.exists(self.usage_path):
                with open(self.usage_path, encoding='utf-8') as stream:
                    usage = json.load(stream)
            if usage['calls'] >= self.max_calls:
                raise RuntimeError('Job model-call limit reached. Review usage.json and job config before resuming.')
            # Reserve before dispatch; failed and interrupted requests also count.
            usage['calls'] += 1
            by_service = usage.setdefault('by_service', {})
            service_usage = by_service.setdefault(service_id, {
                'calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0,
                'response_seconds': 0.0, 'failures': 0,
            })
            service_usage['calls'] += 1
            by_model = usage.setdefault('by_model', {})
            model_usage = by_model.setdefault(model_name, {
                'calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0,
                'response_seconds': 0.0, 'failures': 0,
            })
            model_usage['calls'] += 1
            atomic_json(self.usage_path, usage)
            request_started = time.monotonic()
            response = self.client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=request_output_tokens,
            )
            print(f"[{service_id}] Model response received in {time.monotonic() - request_started:.1f}s.")
            if response.usage:
                prompt_count = response.usage.prompt_tokens or 0
                completion_count = response.usage.completion_tokens or 0
                usage['prompt_tokens'] += prompt_count
                usage['completion_tokens'] += completion_count
                service_usage['prompt_tokens'] += prompt_count
                service_usage['completion_tokens'] += completion_count
                model_usage['prompt_tokens'] += prompt_count
                model_usage['completion_tokens'] += completion_count
            atomic_json(self.usage_path, usage)
            if response.choices[0].finish_reason == 'length':
                provider = getattr(self, 'provider', None)
                if provider == 'ollama':
                    provider_hint = 'for a local model, also check its loaded context length in Ollama.'
                elif provider == 'lmstudio':
                    provider_hint = 'for a local model, also check its loaded context length in LM Studio.'
                elif provider in CLOUD_PROVIDERS:
                    provider_name = PROVIDER_NAMES.get(provider, 'cloud models')
                    provider_hint = f'for {provider_name}, also choose a model with a larger context limit or lower the output limit.'
                else:
                    provider_hint = 'for a local model, also check its loaded context length in LM Studio or Ollama.'
                raise RuntimeError(f'The model reached its response or context limit before finishing. '
                                   f'In Settings, check the output limit; {provider_hint} Then use Resume '
                                   f'with current settings. Repeating this same request unchanged will not fix it.')
            finish_reason = response.choices[0].finish_reason
            if finish_reason == 'error':
                # Providers signal an upstream generation failure with HTTP 200 and
                # finish_reason 'error'. Retry it, and name the cause when we run out.
                raise ValueError(
                    f'empty content: the provider reported a generation error '
                    f'(response id: {getattr(response, "id", "unknown")}). '
                    f'This is usually an upstream capacity or timeout limit on the routed model.')
            content = response.choices[0].message.content
            if not content or not content.strip():
                # A blank completion is almost never the model's fault alone. Report the
                # provider's own reason so the failure is actionable instead of opaque.
                detail = finish_reason or 'unknown'
                provider_message = ''
                try:
                    provider_message = (response.choices[0].message.model_extra or {}).get('provider_metadata') or ''
                except (AttributeError, TypeError):
                    pass
                raise ValueError(
                    f'Model returned empty content (finish_reason: {detail}). '
                    f'The provider ended the generation without text. Lower the output limit in '
                    f'Settings, or pick a model with a higher completion ceiling, then use Resume. '
                    f'{provider_message}'.strip())
            service_usage['response_seconds'] += round(time.monotonic() - request_started, 2)
            model_usage['response_seconds'] += round(time.monotonic() - request_started, 2)
            atomic_json(self.usage_path, usage)
            return content.strip()
        except Exception as e:
            if 'request_started' in locals():
                duration = round(time.monotonic() - request_started, 2)
                print(f"[{service_id}] Request ended after {duration:.1f}s.")
                if 'service_usage' in locals():
                    service_usage['response_seconds'] += duration
                    service_usage['failures'] += 1
                    model_usage['response_seconds'] += duration
                    model_usage['failures'] += 1
                    atomic_json(self.usage_path, usage)
            if isinstance(e, APIConnectionError):
                cause = type(e.__cause__).__name__ if e.__cause__ else 'unknown transport error'
                provider = getattr(self, 'provider', '')
                detail = ('Response timed out. Increase the response timeout or reduce the request size.'
                          if isinstance(e, APITimeoutError) else
                          f'Connection failed. Check your internet connection and {PROVIDER_NAMES.get(provider, "cloud provider")} availability.'
                          if provider in CLOUD_PROVIDERS else
                          'Connection failed. Check that your local model server is running and the model is loaded.')
                message = f'{detail} Transport: {cause}. Saved steps are kept; resume when the connection is ready.'
                print(message)
                raise RuntimeError(message) from e
            print(f"Error calling model API: {e}")
            raise

    async def execute_streaming_prompt(self, service_id: str, system_prompt: str, user_prompt: str, 
                                       on_delta=None) -> str:
        """Execute prompt with streaming for long responses."""
        model_config = self.get_model_for_service(service_id)
        model_name = model_config.get("model", self.default_model)
        temperature = model_config.get("temperature", self.default_temp)
        
        provider_name = PROVIDER_NAMES.get(getattr(self, 'provider', ''), 'OpenRouter')
        print(f"[{service_id}] Streaming from {provider_name} (model: {model_name}, temp: {temperature})...")
        
        try:
            stream = self.client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                stream=True
            )
            
            full_text = ""
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                full_text += delta
                if on_delta:
                    on_delta(delta)
                else:
                    print(delta, end="", flush=True)
            
            print()  # Newline after streaming
            return full_text
        except Exception as e:
            print(f"\nError in streaming call: {e}")
            raise
