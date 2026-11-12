"""Model backends behind one interface (decision D4).

  claude-cli  local development and evals: Claude through the Claude Code CLI with a Claude login, in a clean
              configuration with a usage guard (subscription.py). Custom system prompt, no tools,
              JSON-schema-validated output, screenshots supported. Not used by the deployed app.
  anthropic   the API: the deployed app, and a parity check against the CLI backend.

Every call returns the parsed JSON plus usage, so evals can report tokens and latency per step.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Protocol

from p2p_autopilot import subscription

DEFAULT_MODEL = os.environ.get("LPA_MODEL", "haiku")


@dataclass
class LLMResult:
    data: dict
    input_tokens: int
    output_tokens: int
    latency_s: float
    model: str
    cost_usd: float = 0.0  # API-equivalent cost reported by the CLI (0 when unknown)


class Backend(Protocol):
    def complete(self, system: str, prompt: str, schema: dict, model: str = DEFAULT_MODEL,
                 images: list[bytes] | None = None) -> LLMResult: ...


class ClaudeCLIBackend:
    """`claude -p` through `subscription.run` (clean configuration, never an API key, usage guard). Model id, effort
    and output cap are pinned to what the API backend uses, so both paths send the same request apart from
    authentication."""

    def __init__(self, timeout_s: int = 120, effort: str | None = None):
        self.timeout_s = timeout_s
        self.effort = effort or os.environ.get("LPA_EFFORT")

    def complete(self, system: str, prompt: str, schema: dict, model: str = DEFAULT_MODEL,
                 images: list[bytes] | None = None) -> LLMResult:
        model_id = MODEL_IDS.get(model, model)
        effort = self.effort or API_DEFAULT_EFFORT.get(model_id)
        args = ["-p", "--model", model_id, "--system-prompt", system, "--tools", "", "--setting-sources", "",
                "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
                "--json-schema", json.dumps(schema), "--input-format", "stream-json"]
        if effort:
            args += ["--effort", effort]
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                "data": base64.b64encode(img).decode()}} for img in images or []]
        content.append({"type": "text", "text": prompt})
        msg = json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"
        t0 = time.monotonic()
        err = ""
        for _attempt in (1, 2):  # the CLI occasionally returns an empty answer; one retry, then a clear error
            out, events = subscription.run(args, msg, self.timeout_s)
            result = next((e for e in reversed(events) if e.get("type") == "result"), {})
            data = result.get("structured_output")
            if data is None and str(result.get("result", "")).strip().startswith("{"):
                try:
                    data = json.loads(result["result"])
                except json.JSONDecodeError:
                    data = None
            if out.returncode == 0 and isinstance(data, dict) and not result.get("is_error"):
                u = result.get("usage", {})
                tokens_in = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                             + u.get("cache_read_input_tokens", 0))
                return LLMResult(data, tokens_in, u.get("output_tokens", 0), time.monotonic() - t0, model,
                                 float(result.get("total_cost_usd") or 0.0))
            err = (f"claude CLI gave no structured answer (exit {out.returncode}): "
                   f"{str(result.get('result'))[:200]!r} {out.stderr[-200:]}")
        raise RuntimeError(err)


def _cli_env() -> dict[str, str]:
    """Environment for the CLI backend: no API-key variables (the CLI would bill the key instead of the login) and,
    when the clean setup exists, the isolated config folder and the CLI token. See subscription.py."""
    return subscription.env()


MODEL_IDS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
# the API's default effort per model: the CLI is pinned to the same value when none is configured
API_DEFAULT_EFFORT = {"claude-haiku-5-5": "medium", "claude-sonnet-5-5": "high", "claude-opus-5-5": "medium"}
_UNSUPPORTED = {"minimum", "maximum", "multipleOf", "minLength", "maxLength", "minItems", "maxItems"}


def api_schema(schema: dict) -> dict:
    """Structured outputs need additionalProperties: false on every object and no numeric/array constraints.
    The removed constraints are enforced in our own code (e.g. batches are cut to MAX_BATCH in agent.py)."""
    if isinstance(schema, dict):
        out = {k: api_schema(v) for k, v in schema.items() if k not in _UNSUPPORTED}
        if out.get("type") == "object":
            out["additionalProperties"] = False
        return out
    if isinstance(schema, list):
        return [api_schema(v) for v in schema]
    return schema


class AnthropicBackend:
    """The Claude API (final evals and the live demo). Same interface as the CLI backend.

    The client is injectable so tests run without a key or any spend.
    """

    def __init__(self, client=None, effort: str | None = None, max_tokens: int = 16000):
        if client is None:
            import anthropic  # imported here so the CLI backend works without the package configured
            client = anthropic.Anthropic()
        self.client = client
        self.effort = effort or os.environ.get("LPA_EFFORT")  # None = the model's default
        self.max_tokens = max_tokens

    def complete(self, system: str, prompt: str, schema: dict, model: str = DEFAULT_MODEL,
                 images: list[bytes] | None = None) -> LLMResult:
        import anthropic
        content: list[dict] = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                            "data": base64.standard_b64encode(img).decode()}}
                               for img in images or []]
        content.append({"type": "text", "text": prompt})
        output_config: dict = {"format": {"type": "json_schema", "schema": api_schema(schema)}}
        if self.effort:
            output_config["effort"] = self.effort
        t0 = time.monotonic()
        try:
            resp = self.client.messages.create(
                model=MODEL_IDS.get(model, model), max_tokens=self.max_tokens, system=system,
                messages=[{"role": "user", "content": content}], output_config=output_config)
        except anthropic.RateLimitError as e:
            raise RuntimeError(f"rate limited by the API: {e}") from e
        except anthropic.APIStatusError as e:
            raise RuntimeError(f"API error {e.status_code}: {e}") from e
        except anthropic.APIConnectionError as e:
            raise RuntimeError(f"could not reach the API: {e}") from e
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"model refused: {getattr(resp, 'stop_details', None)}")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("answer cut off at max_tokens")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            raise RuntimeError("no text block in the answer")
        u = resp.usage
        tokens_in = u.input_tokens + (u.cache_creation_input_tokens or 0) + (u.cache_read_input_tokens or 0)
        return LLMResult(json.loads(text), tokens_in, u.output_tokens, time.monotonic() - t0, model)


def get_backend(name: str | None = None) -> Backend:
    """The model backend, wrapped so every call is an LLM span when tracing is configured (p2p_autopilot.tracing)."""
    from p2p_autopilot import tracing
    name = name or os.environ.get("LPA_BACKEND", "claude-cli")
    if name == "claude-cli":
        inner = ClaudeCLIBackend()
    elif name == "anthropic":
        inner = AnthropicBackend()
    else:
        raise ValueError(f"unknown backend {name!r}; use claude-cli or anthropic")
    return tracing.TracedBackend(inner, name) if tracing.setup() else inner
