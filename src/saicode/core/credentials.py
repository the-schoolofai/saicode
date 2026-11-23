"""API keys: environment variable first, then the OS keychain.

On macOS the keychain is the login Keychain, on Windows the Credential
Manager, on Linux the Secret Service (if available). Keys are never written
to saicode's own config files.
"""

from __future__ import annotations

import os

SERVICE = "saicode"

ENV_VARS = {
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
}


def _keyring():
    try:
        import keyring

        return keyring
    except Exception:
        return None


def get_api_key(provider: str) -> tuple[str | None, str]:
    """Return (key, where it came from)."""
    for var in ENV_VARS.get(provider, [f"{provider.upper()}_API_KEY"]):
        value = os.environ.get(var)
        if value:
            return value, f"environment variable {var}"
    kr = _keyring()
    if kr is not None:
        try:
            value = kr.get_password(SERVICE, provider)
        except Exception:
            value = None
        if value:
            return value, "system keychain"
    return None, ""


def store_api_key(provider: str, key: str) -> None:
    kr = _keyring()
    if kr is None:
        raise RuntimeError("No system keychain is available on this computer.")
    kr.set_password(SERVICE, provider, key)


def delete_api_key(provider: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.delete_password(SERVICE, provider)
        return True
    except Exception:
        return False
