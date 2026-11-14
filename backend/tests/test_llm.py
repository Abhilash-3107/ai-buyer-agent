"""LLMClient tests with a fake OpenAI client: no network, no API key."""
from types import SimpleNamespace as NS

import pytest

from app.agent.llm import LLMClient, LLMConfig

CFG = LLMConfig(base_url="http://localhost:11434/v1", api_key="", model="fake", temperature=None)


DEFAULT_USAGE = NS(prompt_tokens=10, completion_tokens=5)


def fake_client(content=None, tool_calls=None, usage=DEFAULT_USAGE):
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


def test_missing_model_fails_fast_naming_the_variable():
    import pytest
    with pytest.raises(RuntimeError, match="LLM_MODEL"):
        LLMClient(LLMConfig(base_url="http://localhost:11434/v1", api_key="", model="", temperature=None))


def test_model_has_no_hidden_default(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert LLMConfig.from_env().model == ""


def test_non_object_tool_json_is_reported_not_raised():
    client, _ = fake_client(tool_calls=[tc("c1", "get_stock", "[]")])
    r = LLMClient(CFG, client=client).chat([{"role": "user", "content": "hi"}])
    assert r.tool_calls[0].parse_error and r.tool_calls[0].arguments == {}


def test_temperature_is_sent_when_configured():
    client, sent = fake_client(content="hi")
    cfg = LLMConfig(base_url=CFG.base_url, api_key="", model="fake", temperature=0.2)
    LLMClient(cfg, client=client).chat([{"role": "user", "content": "hi"}])
    assert sent["temperature"] == 0.2


def test_timeout_is_read_from_env(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_S", "300")
    assert LLMConfig.from_env().timeout_s == 300.0
    monkeypatch.delenv("LLM_TIMEOUT_S")
    assert LLMConfig.from_env().timeout_s == 120.0


def test_invalid_timeout_raises_clear_error(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_S", "soon")
    with pytest.raises(ValueError, match="LLM_TIMEOUT_S"):
        LLMConfig.from_env()


def test_max_tokens_is_sent_on_every_request_and_defaults_to_4096():
    client, sent = fake_client(content="hi")
    LLMClient(CFG, client=client).chat([{"role": "user", "content": "hi"}])
    assert sent["max_tokens"] == 4096
    client, sent = fake_client(content="hi")
    cfg = LLMConfig(base_url=CFG.base_url, api_key="", model="fake", temperature=None, max_tokens=512)
    LLMClient(cfg, client=client).chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
    assert sent["max_tokens"] == 512


def test_hosted_endpoint_sends_max_completion_tokens_instead_of_max_tokens():
    client, sent = fake_client(content="hi")
    cfg = LLMConfig(base_url="https://api.openai.com/v1", api_key="sk-test", model="fake", temperature=None, max_tokens=512)
    LLMClient(cfg, client=client).chat([{"role": "user", "content": "hi"}])
    assert sent["max_completion_tokens"] == 512
    assert "max_tokens" not in sent


def test_reasoning_effort_is_sent_only_when_set(monkeypatch):
    client, sent = fake_client(content="hi")
    LLMClient(CFG, client=client).chat([{"role": "user", "content": "hi"}])
    assert "reasoning_effort" not in sent
    monkeypatch.setenv("LLM_MODEL", "fake")  # hermetic: do not depend on the developer's .env
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "none")
    cfg = LLMConfig.from_env()
    assert cfg.reasoning_effort == "none"
    client, sent = fake_client(content="hi")
    LLMClient(cfg, client=client).chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
    assert sent["reasoning_effort"] == "none"


def test_max_tokens_is_read_from_env(monkeypatch):
    monkeypatch.setenv("LLM_MAX_TOKENS", "1024")
    assert LLMConfig.from_env().max_tokens == 1024
    monkeypatch.delenv("LLM_MAX_TOKENS")
    assert LLMConfig.from_env().max_tokens == 4096


@pytest.mark.parametrize("bad", ["lots", "0", "-5", "1.5"])
def test_invalid_max_tokens_raises_clear_error(monkeypatch, bad):
    monkeypatch.setenv("LLM_MAX_TOKENS", bad)
    with pytest.raises(ValueError, match="LLM_MAX_TOKENS"):
        LLMConfig.from_env()


def test_missing_usage_gives_empty_usage():
    client, _ = fake_client(content="hi", usage=None)
    r = LLMClient(CFG, client=client).chat([{"role": "user", "content": "hi"}])
    assert r.usage == {}


def test_text_only_reply_has_no_tool_calls():
    client, _ = fake_client(content="All good.")
    r = LLMClient(CFG, client=client).chat([{"role": "user", "content": "hi"}])
    assert r.text == "All good." and r.tool_calls == [] and "tool_calls" not in r.message
