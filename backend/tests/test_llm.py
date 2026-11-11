"""LLMClient tests with a fake OpenAI client: no network, no API key."""
from types import SimpleNamespace as NS

from app.llm import LLMClient, LLMConfig

CFG = LLMConfig(base_url="http://localhost:11434/v1", api_key="", model="fake", temperature=None)


def fake_client(content=None, tool_calls=None, usage=NS(prompt_tokens=10, completion_tokens=5)):
    resp = NS(model="fake", usage=usage,
              choices=[NS(finish_reason="tool_calls" if tool_calls else "stop",
                          message=NS(content=content, tool_calls=tool_calls))])
    captured = {}
    def create(**kw):
        captured.update(kw)
        return resp
    return NS(chat=NS(completions=NS(create=create))), captured


def tc(id_, name, args):
    return NS(id=id_, function=NS(name=name, arguments=args))


def test_parses_tool_calls_and_builds_history_message():
    client, sent = fake_client(tool_calls=[tc("c1", "get_stock", '{"sku": "SKU-1"}')])
    r = LLMClient(CFG, client=client).chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
    assert r.tool_calls[0].arguments == {"sku": "SKU-1"} and r.tool_calls[0].parse_error is None
    assert r.message["tool_calls"][0]["function"]["name"] == "get_stock"
    assert "temperature" not in sent          # not sent unless configured
    assert sent["tool_choice"] == "auto"


def test_malformed_tool_json_is_reported_not_raised():
    client, _ = fake_client(tool_calls=[tc("c1", "get_stock", '{"sku": SKU-1')])
    r = LLMClient(CFG, client=client).chat([{"role": "user", "content": "hi"}])
    assert r.tool_calls[0].parse_error and r.tool_calls[0].arguments == {}


def test_missing_key_for_remote_provider_fails_fast():
    import pytest
    with pytest.raises(RuntimeError):
        LLMClient(LLMConfig(base_url="https://api.openai.com/v1", api_key="", model="x", temperature=None))


def test_non_object_tool_json_is_reported_not_raised():
    client, _ = fake_client(tool_calls=[tc("c1", "get_stock", "[]")])
    r = LLMClient(CFG, client=client).chat([{"role": "user", "content": "hi"}])
    assert r.tool_calls[0].parse_error and r.tool_calls[0].arguments == {}


def test_temperature_is_sent_when_configured():
    client, sent = fake_client(content="hi")
    cfg = LLMConfig(base_url=CFG.base_url, api_key="", model="fake", temperature=0.2)
    LLMClient(cfg, client=client).chat([{"role": "user", "content": "hi"}])
    assert sent["temperature"] == 0.2


def test_missing_usage_gives_empty_usage():
    client, _ = fake_client(content="hi", usage=None)
    r = LLMClient(CFG, client=client).chat([{"role": "user", "content": "hi"}])
    assert r.usage == {}


def test_text_only_reply_has_no_tool_calls():
    client, _ = fake_client(content="All good.")
    r = LLMClient(CFG, client=client).chat([{"role": "user", "content": "hi"}])
    assert r.text == "All good." and r.tool_calls == [] and "tool_calls" not in r.message
