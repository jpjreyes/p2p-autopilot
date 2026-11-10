"""Model backends behind one interface (decision D4).

  claude-cli  development: runs `claude -p` on a Claude plan. No tools, no hooks, no MCP, no session
              files, a custom system prompt and JSON-schema-validated output. Not for the live demo.
  anthropic   the API (final evals and live demo); used when ANTHROPIC_API_KEY is set.

Every call returns the parsed JSON plus usage, so evals can report tokens and latency per step.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Protocol

DEFAULT_MODEL = os.environ.get("LPA_MODEL", "haiku")


@dataclass
class LLMResult:
    data: dict
    input_tokens: int
    output_tokens: int
    latency_s: float
    model: str


class Backend(Protocol):
    def complete(self, system: str, prompt: str, schema: dict, model: str = DEFAULT_MODEL,
                 images: list[bytes] | None = None) -> LLMResult: ...


class ClaudeCLIBackend:
    def __init__(self, timeout_s: int = 120):
        self.timeout_s = timeout_s

    def complete(self, system: str, prompt: str, schema: dict, model: str = DEFAULT_MODEL,
                 images: list[bytes] | None = None) -> LLMResult:
        base = ["claude", "-p", "--model", model, "--system-prompt", system, "--tools", "", "--setting-sources", "",
                "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
                "--json-schema", json.dumps(schema)]
        if images:
            return self._with_images(base, prompt, images, model)
        cmd = [*base[:2], prompt, *base[2:], "--output-format", "json"]
        t0 = time.monotonic()
        for attempt in (1, 2):  # the CLI occasionally returns an empty answer; one retry, then a clear error
            out = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=self.timeout_s,
                                 cwd="/tmp", env=_cli_env())
            if out.returncode != 0:
                err = f"claude CLI failed ({out.returncode}): {out.stderr[-300:] or out.stdout[-300:]}"
            else:
                payload = json.loads(out.stdout)
                data = payload.get("structured_output")
                if data is None and payload.get("result", "").strip().startswith("{"):
                    data = json.loads(payload["result"])
                if not payload.get("is_error") and isinstance(data, dict):
                    break
                err = f"claude CLI gave no structured answer: {str(payload.get('result'))[:200]!r}"
            if attempt == 2:
                raise RuntimeError(err)
        latency = time.monotonic() - t0
        u = payload.get("usage", {})
        tokens_in = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get(
            "cache_read_input_tokens", 0)
        return LLMResult(data, tokens_in, u.get("output_tokens", 0), latency, model)


    def _with_images(self, base: list[str], prompt: str, images: list[bytes], model: str) -> LLMResult:
        """Images need the stream-json input format (one user message with image blocks)."""
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                "data": base64.b64encode(img).decode()}} for img in images]
        content.append({"type": "text", "text": prompt})
        msg = json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"
        cmd = [*base, "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
        t0 = time.monotonic()
        for attempt in (1, 2):
            out = subprocess.run(cmd, check=False, input=msg, capture_output=True, text=True,
                                 timeout=self.timeout_s, cwd="/tmp", env=_cli_env())
            events = [json.loads(ln) for ln in out.stdout.splitlines() if ln.strip().startswith("{")]
            result = next((e for e in reversed(events) if e.get("type") == "result"), {})
            data = result.get("structured_output")
            if out.returncode == 0 and isinstance(data, dict) and not result.get("is_error"):
                u = result.get("usage", {})
                tokens_in = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                             + u.get("cache_read_input_tokens", 0))
                return LLMResult(data, tokens_in, u.get("output_tokens", 0), time.monotonic() - t0, model)
            if attempt == 2:
                raise RuntimeError(f"claude CLI (images) gave no structured answer: {out.stderr[-200:]}")
        raise AssertionError("unreachable")


def _cli_env() -> dict[str, str]:
    """The CLI backend must run on the developer's Claude login. If ANTHROPIC_API_KEY were inherited (e.g. from .env),
    `claude -p` would silently bill the API instead, so it is removed here; only the anthropic backend uses the key."""
    return {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}


MODEL_IDS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
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
    name = name or os.environ.get("LPA_BACKEND", "claude-cli")
    if name == "claude-cli":
        return ClaudeCLIBackend()
    if name == "anthropic":
        return AnthropicBackend()
    raise ValueError(f"unknown backend {name!r}; use claude-cli or anthropic")
