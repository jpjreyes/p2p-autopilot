"""The API backend with a fake client: request shape, schema rewriting, stop reasons. No key, no spend."""

import json
from types import SimpleNamespace

import pytest

from legacy_portal.agent import ACTION_SCHEMA
from legacy_portal.llm import AnthropicBackend, api_schema


class FakeMessages:
    def __init__(self, reply: dict, stop_reason: str = "end_turn"):
        self.reply, self.stop_reason, self.calls = reply, stop_reason, []

    def create(self, **kw):
        self.calls.append(kw)
        usage = SimpleNamespace(input_tokens=100, output_tokens=20, cache_creation_input_tokens=0,
                                cache_read_input_tokens=50)
        return SimpleNamespace(stop_reason=self.stop_reason, usage=usage, stop_details=None,
                               content=[SimpleNamespace(type="text", text=json.dumps(self.reply))])


def backend(reply, stop_reason="end_turn"):
    fake = FakeMessages(reply, stop_reason)
    return AnthropicBackend(client=SimpleNamespace(messages=fake)), fake


def test_schema_is_rewritten_for_structured_outputs():
    s = api_schema(ACTION_SCHEMA)
    assert s["additionalProperties"] is False
    items = s["properties"]["actions"]
    assert "maxItems" not in items and "minItems" not in items
    assert items["items"]["additionalProperties"] is False and "minimum" not in str(items)


def test_request_shape_model_id_image_and_usage():
    b, fake = backend({"actions": [{"action": "done"}], "reason": "ok"})
    r = b.complete("sys", "page", ACTION_SCHEMA, model="haiku", images=[b"\x89PNG..."])
    call = fake.calls[0]
    assert call["model"] == "claude-haiku-5-5" and call["system"] == "sys"
    assert call["output_config"]["format"]["type"] == "json_schema"
    blocks = call["messages"][0]["content"]
    assert blocks[0]["type"] == "image" and blocks[-1] == {"type": "text", "text": "page"}
    assert r.data["actions"][0]["action"] == "done" and r.input_tokens == 150 and r.output_tokens == 20


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_refusal_and_truncation_raise_so_the_agent_stops_safely(stop):
    b, _ = backend({"actions": []}, stop_reason=stop)
    with pytest.raises(RuntimeError):
        b.complete("s", "p", ACTION_SCHEMA)


def test_cli_backend_never_passes_the_api_key(monkeypatch):
    from legacy_portal.llm import _cli_env
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert "ANTHROPIC_API_KEY" not in _cli_env()
