"""Model providers behind one interface, with an administrator allowlist."""

from __future__ import annotations

from saicode.ai.base import Provider, ProviderError
from saicode.core.config import Config
from saicode.core.credentials import get_api_key

KNOWN_PROVIDERS = ("gemini",)


class ProviderNotAllowed(Exception):
    pass


class MissingCredentials(Exception):
    pass


def create_provider(config: Config) -> Provider:
    name = config.get("model.provider", "gemini")
    allowed = config.get("providers.allowed", [])
    if name not in allowed:
        raise ProviderNotAllowed(
            f"Provider '{name}' is not allowed by your configuration "
            f"(allowed: {', '.join(allowed) or 'none'})."
        )
    if name not in KNOWN_PROVIDERS:
        raise ProviderNotAllowed(f"Provider '{name}' is not supported yet.")
    key, _source = get_api_key(name)
    if not key:
        raise MissingCredentials(name)
    if name == "gemini":
        from saicode.ai.gemini import GeminiProvider

        return GeminiProvider(key)
    raise ProviderNotAllowed(name)


__all__ = [
    "MissingCredentials",
    "Provider",
    "ProviderError",
    "ProviderNotAllowed",
    "create_provider",
]
