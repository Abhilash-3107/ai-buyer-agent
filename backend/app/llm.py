"""The ONE place the app talks to a language model.

Every other module calls `LLMClient.chat(...)` and gets back a provider-neutral
`LLMResponse`. Swapping OpenAI <-> a local Ollama model (Qwen, etc.) is a change
to three env vars (LLM_BASE_URL / LLM_API_KEY / LLM_MODEL), never to code.

Why Chat Completions (not OpenAI's newer Responses API)?
    It's the lowest common denominator: OpenAI, Ollama, vLLM, LM Studio, Groq,
    Together ... all speak it, including tool/function calling. Portability beats
    the extra features we wouldn't use.

Why parse tool arguments here?
    Small local models sometimes emit malformed JSON for tool arguments. Instead
    of crashing, we return the ToolCall with `parse_error` set, so the agent loop
    can send the error back to the model and let it retry (same feedback-loop
    idea as the PO validator, one layer down).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str
    parse_error: str | None = None   # set when the model produced invalid JSON


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall]
    finish_reason: str | None
    # The assistant message in Chat Completions format - append this to the
    # conversation history as-is before adding tool results.
    message: dict[str, Any]
    usage: dict[str, int] = field(default_factory=dict)
    latency_s: float = 0.0
    model: str = ""


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    temperature: float | None
    timeout_s: float = 120.0
    max_retries: int = 2
    max_tokens: int = 4096
    reasoning_effort: str | None = None  # e.g. "none"; sent only when set

    @classmethod
    def from_env(cls) -> LLMConfig:
        temp = os.getenv("LLM_TEMPERATURE")
        try:
            temperature = float(temp) if temp not in (None, "") else None
        except ValueError:
            raise ValueError(f"LLM_TEMPERATURE must be a number (e.g. 0.2), got {temp!r}") from None
        raw_timeout = os.getenv("LLM_TIMEOUT_S")
        try:
            timeout_s = float(raw_timeout) if raw_timeout not in (None, "") else cls.timeout_s
        except ValueError:
            raise ValueError(f"LLM_TIMEOUT_S must be a number of seconds (e.g. 300), got {raw_timeout!r}") from None
        if timeout_s <= 0:
            raise ValueError(f"LLM_TIMEOUT_S must be greater than 0, got {raw_timeout!r}")
        raw_max = os.getenv("LLM_MAX_TOKENS")
        try:
            max_tokens = int(raw_max) if raw_max not in (None, "") else cls.max_tokens
        except ValueError:
            raise ValueError(f"LLM_MAX_TOKENS must be a whole number of tokens (e.g. 4096), got {raw_max!r}") from None
        if max_tokens <= 0:
            raise ValueError(f"LLM_MAX_TOKENS must be greater than 0, got {raw_max!r}")
        return cls(
            base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            api_key=os.getenv("LLM_API_KEY", ""),
            model=os.getenv("LLM_MODEL", ""),  # no default: the caller must name the model
            temperature=temperature,
            timeout_s=timeout_s,
            max_tokens=max_tokens,
            reasoning_effort=os.getenv("LLM_REASONING_EFFORT") or None,
        )

    @property
    def is_local(self) -> bool:
        return "localhost" in self.base_url or "127.0.0.1" in self.base_url


class LLMClient:
    def __init__(self, config: LLMConfig | None = None, *, client: Any = None):
        self.config = config or LLMConfig.from_env()
        if not self.config.model:
            raise RuntimeError("LLM_MODEL is not set. Set it in .env (see .env.example) or pass --model.")
        if not self.config.api_key and not self.config.is_local:
            raise RuntimeError("LLM_API_KEY is not set. Copy .env.example to .env and fill it in.")
        # `client` is injectable so tests can use a fake without network calls.
        self._client = client or OpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key or "local",
            timeout=self.config.timeout_s,
            max_retries=self.config.max_retries,  # SDK retries 429 / 5xx / connection errors
        )

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMResponse:
        # OpenAI's newer models reject `max_tokens` and want `max_completion_tokens`;
        # Ollama's OpenAI-compatible endpoint only reads `max_tokens`.
        limit_key = "max_tokens" if self.config.is_local else "max_completion_tokens"
        kwargs: dict[str, Any] = {"model": self.config.model, "messages": messages, limit_key: self.config.max_tokens}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if self.config.temperature is not None:
            kwargs["temperature"] = self.config.temperature
        if self.config.reasoning_effort:
            kwargs["reasoning_effort"] = self.config.reasoning_effort

        started = time.perf_counter()
        resp = self._client.chat.completions.create(**kwargs)
        latency = time.perf_counter() - started

        if not resp.choices:
            raise RuntimeError("The LLM returned no choices (empty response); check the model name and provider.")
        choice = resp.choices[0]
        msg = choice.message
        calls = [_parse_tool_call(tc) for tc in (msg.tool_calls or [])]

        assistant_message: dict[str, Any] = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            assistant_message["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]

        usage = {}
        if getattr(resp, "usage", None):
            usage = {"input_tokens": resp.usage.prompt_tokens, "output_tokens": resp.usage.completion_tokens}

        return LLMResponse(text=msg.content, tool_calls=calls, finish_reason=choice.finish_reason,
                           message=assistant_message, usage=usage, latency_s=latency, model=resp.model)


def _parse_tool_call(tc: Any) -> ToolCall:
    raw = tc.function.arguments or "{}"
    try:
        args = json.loads(raw)
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")  # noqa: TRY004 - caught below, reported as parse_error
        return ToolCall(id=tc.id, name=tc.function.name, arguments=args, raw_arguments=raw)
    except (json.JSONDecodeError, ValueError) as e:
        return ToolCall(id=tc.id, name=tc.function.name, arguments={}, raw_arguments=raw,
                        parse_error=f"Invalid JSON arguments: {e}")


def tool_result_message(call_id: str, content: Any) -> dict[str, Any]:
    """Format a tool's output as the Chat Completions 'tool' message."""
    return {"role": "tool", "tool_call_id": call_id,
            "content": content if isinstance(content, str) else json.dumps(content, default=str)}


if __name__ == "__main__":
    # Smoke test:  uv run python -m app.llm
    cfg = LLMConfig.from_env()
    print(f"model={cfg.model} base_url={cfg.base_url}")
    stock_tool = {"type": "function", "function": {
        "name": "get_stock", "description": "Get on-hand stock for a SKU",
        "parameters": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]}}}
    r = LLMClient(cfg).chat([{"role": "user", "content": "How much stock of SKU-1002 do we have? Use the tool."}],
                            tools=[stock_tool])
    print(f"latency={r.latency_s:.1f}s finish={r.finish_reason} usage={r.usage}")
    print("text:", r.text)
    for c in r.tool_calls:
        print("tool_call:", c.name, c.arguments, c.parse_error or "")
