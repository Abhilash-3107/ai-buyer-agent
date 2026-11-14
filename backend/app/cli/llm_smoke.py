"""CLI: one real model call with a tool, to check the endpoint, key and tool calling.

    uv run buyer-llm-smoke
"""
from __future__ import annotations

from ..agent.llm import LLMClient, LLMConfig
from ..config import load_env


def main() -> None:
    load_env()
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


if __name__ == "__main__":
    main()
