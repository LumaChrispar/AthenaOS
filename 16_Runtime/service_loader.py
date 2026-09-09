import os
import yaml
import re
import json

# Service cache for performance (P1)
class ServiceCache:
    _instance = None
    _cache = {}
    
    @classmethod
    def get(cls, key: str):
        return cls._cache.get(key)
    
    @classmethod
    def set(cls, key: str, value):
        cls._cache[key] = value
        return value
    
    @classmethod
    def invalidate(cls, key: str):
        """Call after StoryBibleUpdated event."""
        cls._cache.pop(key, None)
    
    @classmethod
    def clear(cls):
        cls._cache.clear()

def load_service(service_id: str, base_dir: str) -> dict:
    """
    Reads an SRV-xxx.md file and extracts its core components.
    Returns a dict with 'identity', 'philosophy', and 'contract' (the json block).
    Uses caching for performance.
    """
    cache_key = f"service_{service_id}"
    cached = ServiceCache.get(cache_key)
    if cached:
        return cached
    
    filepath = os.path.join(base_dir, "06_Services", f"{service_id}.md")
    
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Service file not found: {filepath}")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract sections using regex
    identity_match = re.search(r'## Identity\n(.*?)\n## ', content, re.DOTALL)
    philosophy_match = re.search(r'## Core Philosophy\n(.*?)\n## ', content, re.DOTALL)
    
    # The rest of the document (rules, protocols, etc.) before the interface contract
    full_body_match = re.search(r'(## Identity.*?)## Interface Contract', content, re.DOTALL)
    
    contract_match = re.search(r'## Interface Contract.*?```json\n(.*?)\n```', content, re.DOTALL)

    import json
    contract_data = {}
    if contract_match:
        try:
            contract_data = json.loads(contract_match.group(1))
        except json.JSONDecodeError as e:
            print(f"Warning: Failed to parse Interface Contract JSON in {service_id}: {e}")

    result = {
        "service_id": service_id,
        "full_prompt": content,
        "identity": identity_match.group(1).strip() if identity_match else "",
        "philosophy": philosophy_match.group(1).strip() if philosophy_match else "",
        "contract": contract_data
    }
    
    return ServiceCache.set(cache_key, result)

def format_system_prompt(service_data: dict) -> str:
    """Converts the extracted service data into a system prompt for the LLM."""
    return f"""You are AthenaOS Service {service_data['service_id']}.

{service_data['full_prompt']}

---
**OUTPUT REQUIREMENTS:**
You must fulfill your Interface Contract. You must output the required data in valid JSON format only, surrounded by ```json ... ``` tags. Do not output conversational filler.
"""

def invalidate_service_cache(service_id: str = None):
    """Invalidate cache for a specific service or all services."""
    if service_id:
        ServiceCache.invalidate(f"service_{service_id}")
    else:
        ServiceCache.clear()
