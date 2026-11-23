"""Gemini provider (Google AI Studio API key)."""

from __future__ import annotations

import re
from typing import Any

from google import genai
from google.genai import errors, types

from saicode.ai.base import ProviderError, Reply, ToolCall, ToolResult, ToolSpec, Usage


def _retry_delay(e: errors.APIError) -> int | None:
    try:
        details = (e.details or {}).get("error", {}).get("details", [])
        for d in details:
            if "retryDelay" in d:
                return int(float(str(d["retryDelay"]).rstrip("s")))
    except Exception:
        pass
    m = re.search(r"retry in ([\d.]+)s", e.message or "")
    return int(float(m.group(1))) if m else None


def translate(e: Exception) -> ProviderError:
    if isinstance(e, errors.APIError):
        msg = e.message or str(e)
        code = e.code
        if code == 429:
            return ProviderError(
                "quota",
                msg,
                code=code,
                retry_after=_retry_delay(e),
                free_tier="free_tier" in msg,
                no_quota="limit: 0" in msg,
                daily="per day" in msg.lower() or "PerDay" in str(e.details),
            )
        if code == 400 and "API key" in msg:
            return ProviderError("auth", msg, code=code)
        if code in (401,):
            return ProviderError("auth", msg, code=code)
        if code == 403:
            return ProviderError("permission", msg, code=code)
        if code == 404:
            return ProviderError("not_found", msg, code=code)
        if code and code >= 500:
            return ProviderError("server", msg, code=code)
        return ProviderError("other", msg, code=code)
    return ProviderError("network", f"{type(e).__name__}: {e}")


def _reply(resp: Any) -> Reply:
    text = ""
    try:
        parts = resp.candidates[0].content.parts or []
        text = "".join(
            p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False)
        )
    except (AttributeError, IndexError, TypeError):
        pass
    calls = [
        ToolCall(name=c.name, args=dict(c.args or {}), id=getattr(c, "id", None))
        for c in (resp.function_calls or [])
    ]
    usage = Usage()
    if getattr(resp, "usage_metadata", None):
        usage = Usage(
            resp.usage_metadata.prompt_token_count or 0,
            resp.usage_metadata.candidates_token_count or 0,
        )
    return Reply(text=text, tool_calls=calls, usage=usage)


class GeminiChat:
    def __init__(self, chat: Any):
        self._chat = chat

    def send(self, message: str) -> Reply:
        try:
            return _reply(self._chat.send_message(message))
        except Exception as e:
            raise translate(e) from e

    def send_tool_results(self, results: list[ToolResult]) -> Reply:
        parts = [
            types.Part.from_function_response(name=r.call.name, response={"result": r.output})
            for r in results
        ]
        try:
            return _reply(self._chat.send_message(parts))
        except Exception as e:
            raise translate(e) from e

    def history(self) -> Any:
        return self._chat.get_history()


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str):
        # Preview models (e.g. gemini-3.1-pro-preview) are served on v1beta.
        self.client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(api_version="v1beta")
        )

    def start_chat(
        self, model: str, system: str, tools: list[ToolSpec], history: Any = None
    ) -> GeminiChat:
        decls = [
            types.FunctionDeclaration(
                name=t.name, description=t.description, parameters_json_schema=t.parameters
            )
            for t in tools
        ]
        chat = self.client.chats.create(
            model=model,
            history=history or [],
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=[types.Tool(function_declarations=decls)],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        return GeminiChat(chat)

    def list_models(self) -> list[str]:
        try:
            names = [
                m.name.replace("models/", "")
                for m in self.client.models.list()
                if m.name and "generateContent" in (m.supported_actions or [])
            ]
        except Exception as e:
            raise translate(e) from e
        return sorted(names, reverse=True)

    def check_model(self, model: str) -> None:
        try:
            self.client.models.get(model=model)
        except Exception as e:
            raise translate(e) from e
