"""Adaptadores de LLM contra servidores HTTP simulados no formato real de cada API."""
import json

import httpx
import pytest

from app.config import settings
from app.llm.client import LLMClient, LLMError, get_client, status

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"], "additionalProperties": False}
KEY = "sk-SEGREDO-123456"


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    for k, v in dict(llm_provider="none", llm_model="", llm_base_url="", anthropic_api_key=KEY, openai_api_key=KEY,
                     openrouter_api_key=KEY, ollama_host="http://ollama.local:11434").items():
        monkeypatch.setattr(settings, k, v)


def client(handler, provider, model="m1", monkeypatch=None):
    settings.llm_provider, settings.llm_model = provider, model
    return LLMClient(http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)


def test_none_makes_no_network_call_and_has_no_client():
    assert get_client() is None
    st = status()
    assert st["provider"] == "none" and st["external"] is False and not st["configured"]


def test_anthropic_request_shape_and_parse():
    seen = {}

    def h(req):
        seen.update(url=str(req.url), headers=req.headers, body=json.loads(req.content))
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}, {"type": "tool_use", "name": "resposta", "input": {"x": 7}}],
                                         "usage": {"input_tokens": 11, "output_tokens": 5}, "stop_reason": "tool_use"})
    r = client(h, "anthropic", "").complete_json("SYS", "USER", SCHEMA)
    assert r.data == {"x": 7} and (r.input_tokens, r.output_tokens) == (11, 5) and r.raw_provider == "anthropic/claude-sonnet-5-5"
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == KEY and seen["headers"]["anthropic-version"] == "2023-06-01"
    b = seen["body"]
    assert b["system"] == "SYS" and b["messages"] == [{"role": "user", "content": "USER"}]
    assert b["tools"][0]["input_schema"] == SCHEMA and b["tool_choice"] == {"type": "tool", "name": "resposta"} and b["temperature"] == 0


def test_anthropic_retries_without_rejected_temperature_and_on_429():
    calls = []

    def h(req):
        body = json.loads(req.content)
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "1"}, json={"error": "rate"})
        if "temperature" in body:
            return httpx.Response(400, json={"error": {"message": "temperature is not supported for this model"}})
        return httpx.Response(200, json={"content": [{"type": "tool_use", "input": {"x": 1}}], "usage": {}})
    c = client(h, "anthropic")
    assert c.complete_json("s", "u", SCHEMA).data == {"x": 1}
    assert len(calls) == 3 and "temperature" not in calls[-1]
    assert c._no_temperature is True  # lembra para as próximas chamadas


def test_anthropic_truncation_and_missing_tool_are_errors():
    c = client(lambda r: httpx.Response(200, json={"content": [], "stop_reason": "max_tokens"}), "anthropic")
    with pytest.raises(LLMError, match="truncada"):
        c.complete_json("s", "u", SCHEMA)
    c = client(lambda r: httpx.Response(200, json={"content": [{"type": "text", "text": "oi"}]}), "anthropic")
    with pytest.raises(LLMError, match="ferramenta"):
        c.complete_json("s", "u", SCHEMA)


def test_openai_uses_strict_json_schema_and_parses():
    seen = {}

    def h(req):
        seen.update(url=str(req.url), auth=req.headers["authorization"], body=json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"x": 3}'}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 20, "completion_tokens": 4}})
    r = client(h, "openai", "gpt-x").complete_json("SYS", "USER", SCHEMA, name="plano")
    assert r.data == {"x": 3} and (r.input_tokens, r.output_tokens) == (20, 4)
    assert seen["url"] == "https://api.openai.com/v1/chat/completions" and seen["auth"] == f"Bearer {KEY}"
    b = seen["body"]
    assert b["response_format"] == {"type": "json_schema", "json_schema": {"name": "plano", "schema": SCHEMA, "strict": True}}
    assert [m["role"] for m in b["messages"]] == ["system", "user"] and "max_completion_tokens" in b and b["model"] == "gpt-x"


def test_openai_degrades_when_model_rejects_json_schema():
    modes = []

    def h(req):
        rf = json.loads(req.content).get("response_format")
        modes.append(rf["type"] if rf else "plain")
        if rf and rf["type"] != "json_object":
            return httpx.Response(400, json={"error": {"message": "response_format json_schema is not supported by this model"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n{\"x\": 2}\n```"}, "finish_reason": "stop"}], "usage": {}})
    c = client(h, "openai", "gpt-old")
    assert c.complete_json("s", "u", SCHEMA).data == {"x": 2}
    assert modes == ["json_schema", "json_object"]
    c.complete_json("s", "u", SCHEMA)
    assert modes[2:] == ["json_object"]  # não insiste no modo que já falhou


def test_openai_refusal_and_length_are_errors():
    c = client(lambda r: httpx.Response(200, json={"choices": [{"message": {"refusal": "não posso"}, "finish_reason": "stop"}]}), "openai", "g")
    with pytest.raises(LLMError, match="recusou"):
        c.complete_json("s", "u", SCHEMA)
    c = client(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "{"}, "finish_reason": "length"}]}), "openai", "g")
    with pytest.raises(LLMError, match="truncada"):
        c.complete_json("s", "u", SCHEMA)


def test_openrouter_base_url_headers_and_max_tokens():
    seen = {}

    def h(req):
        seen.update(url=str(req.url), headers=req.headers, body=json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"x":1}'}, "finish_reason": "stop"}], "usage": {}})
    client(h, "openrouter", "anthropic/claude-x").complete_json("s", "u", SCHEMA)
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["headers"]["x-title"] == "Kontrul Editor" and "http-referer" in seen["headers"]
    assert "max_tokens" in seen["body"] and "max_completion_tokens" not in seen["body"]


def test_ollama_local_format_and_options():
    seen = {}

    def h(req):
        seen.update(url=str(req.url), body=json.loads(req.content), auth=req.headers.get("authorization"))
        return httpx.Response(200, json={"message": {"content": '{"x": 9}'}, "done_reason": "stop", "prompt_eval_count": 30, "eval_count": 8})
    r = client(h, "ollama", "llama3.1:8b").complete_json("s", "u", SCHEMA)
    assert r.data == {"x": 9} and (r.input_tokens, r.output_tokens) == (30, 8)
    assert seen["url"] == "http://ollama.local:11434/api/chat" and seen["auth"] is None  # sem chave
    b = seen["body"]
    assert b["stream"] is False and b["format"] == SCHEMA and b["options"]["temperature"] == 0 and b["options"]["num_ctx"] == settings.ollama_num_ctx


def test_ollama_down_gives_actionable_message():
    def h(req):
        raise httpx.ConnectError("recusada")
    with pytest.raises(LLMError, match="ollama pull"):
        client(h, "ollama", "llama3.1:8b").complete_json("s", "u", SCHEMA)


def test_api_key_never_leaks_in_errors():
    c = client(lambda r: httpx.Response(401, json={"error": f"invalid key {KEY}"}), "openai", "g")
    with pytest.raises(LLMError) as e:
        c.complete_json("s", "u", SCHEMA)
    assert KEY not in str(e.value) and "401" in str(e.value)
    assert KEY not in json.dumps(status())


def test_misconfiguration_is_reported_not_crashed(monkeypatch):
    settings.llm_provider, settings.llm_model = "openrouter", ""
    assert get_client() is None and "KONTRUL_LLM_MODEL" in status()["message"]
    settings.llm_provider, settings.llm_model, settings.openai_api_key = "openai", "m", ""
    assert get_client() is None and "chave" in status()["message"]
    settings.llm_provider = "inexistente"
    assert get_client() is None and "desconhecido" in status()["message"]


def test_transient_failure_exhausts_retries_cleanly():
    n = []

    def h(req):
        n.append(1)
        return httpx.Response(503, text="indisponível")
    with pytest.raises(LLMError, match="após novas tentativas"):
        client(h, "anthropic").complete_json("s", "u", SCHEMA)
    assert len(n) == 4


def test_status_marks_external_vs_local():
    settings.llm_provider, settings.llm_model = "anthropic", ""
    assert status()["external"] is True and "enviado" in status()["message"]
    settings.llm_provider, settings.llm_model = "ollama", "llama3.1:8b"
    assert status()["external"] is False and "Nada sai" in status()["message"]
