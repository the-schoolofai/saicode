from __future__ import annotations

from google.genai import errors

from saicode.ai.gemini import GeminiProvider, translate
from saicode.tools import specs


def api_error(code: int, message: str, details=None):
    body = {"error": {"code": code, "message": message, "status": "X", "details": details or []}}
    return errors.ClientError(code, body)


def test_free_tier_quota_is_recognised():
    e = translate(
        api_error(
            429,
            "Quota exceeded for metric: generate_content_free_tier_requests, "
            "limit: 0, model: gemini-3.1-pro ... per day limit exceeded",
            [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "78636s"}],
        )
    )
    assert (e.kind, e.free_tier, e.no_quota, e.daily, e.retry_after) == (
        "quota",
        True,
        True,
        True,
        78636,
    )


def test_per_minute_quota_has_short_retry():
    e = translate(api_error(429, "Too many requests. Please retry in 12.5s"))
    assert e.kind == "quota" and e.retry_after == 12 and not e.daily


def test_error_kinds():
    assert (
        translate(api_error(400, "API key not valid. Please pass a valid API key.")).kind == "auth"
    )
    assert translate(api_error(403, "denied")).kind == "permission"
    assert translate(api_error(404, "models/x is not found")).kind == "not_found"
    assert translate(ConnectionError("down")).kind == "network"


def test_chat_builds_with_tool_schemas():
    provider = GeminiProvider(api_key="test-key")
    assert provider.client._api_client._http_options.api_version == "v1beta"
    chat = provider.start_chat("gemini-3-flash-preview", "system", specs())
    assert chat is not None
