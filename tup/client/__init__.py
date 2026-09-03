"""TUP client layer: OpenRouter wrapper, provider registry, response cache.

The runner and the judge import from here and never touch the OpenAI SDK directly::

    from tup.client import OpenRouterClient, ResponseCache
    client = OpenRouterClient(cache=ResponseCache())
    client.validate_models()                       # startup: slugs live?
    reply = client.complete("advisor", messages, provider="openai")
"""
from tup.client.cache import ResponseCache
from tup.client.config import load_api_key, load_base_url, load_config
from tup.client.provider import ConstraintError, ProviderRegistry
from tup.client.openrouter import OpenRouterClient
from tup.client.types import ClientResponse, Config, Sampling, Usage

__all__ = [
    "OpenRouterClient",
    "ResponseCache",
    "ProviderRegistry",
    "ConstraintError",
    "load_config",
    "load_api_key",
    "load_base_url",
    "Config",
    "Sampling",
    "Usage",
    "ClientResponse",
]
