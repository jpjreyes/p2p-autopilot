"""Tracing (OpenTelemetry), the same module design as Contract Radar's: one trace per agent run.

    agent_run ─┬─ llm               (model, tokens, cost, seconds)       one per navigation call
               ├─ browser.action    (action, target, ok, result)         one per click / fill / download
               └─ ...
    process_run ─┬─ document ─┬─ llm (extraction)
                 │            └─ match (verdict, payable)
                 └─ ...
    weekly_brief ─┬─ sql (one per section) ─ llm (summary) ─ grounding

Spans follow the OpenTelemetry GenAI conventions for model calls (gen_ai.*) and OpenInference span kinds so LLM-aware
viewers (Arize Phoenix locally) lay them out; any OTLP backend works (Cloud Trace on GCP). Off unless an endpoint is
configured. Spans carry ids, counts, verdicts, tokens, cost and timing, never invoice text or credentials.

Local viewer:  uvx --python 3.12 --from "arize-phoenix==21.0.0" phoenix serve   (UI on http://localhost:6006)
Then:          LPA_TRACE_ENDPOINT=http://localhost:6006/v1/traces uv run python -m legacy_portal.agent --portal a
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace

_configured = False
tracer = trace.get_tracer("p2p_autopilot")
PRICES = {"haiku": (0.10, 0.50)}  # USD per million tokens (input, output): the same constants as chaos_suite.usd


def setup(service: str = "p2p-autopilot") -> bool:
    """Install an OTLP exporter if LPA_TRACE_ENDPOINT (or the standard OTEL variable) is set. Idempotent."""
    global _configured
    endpoint = os.environ.get("LPA_TRACE_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if _configured or not endpoint:
        return _configured
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    _configured = True
    return True


@contextmanager
def span(name: str, kind: str = "CHAIN", **attrs) -> Iterator[trace.Span]:
    """A span with an OpenInference kind and plain attributes (None values are dropped)."""
    with tracer.start_as_current_span(name) as s:
        s.set_attribute("openinference.span.kind", kind)
        for k, v in attrs.items():
            if v is not None:
                s.set_attribute(k, v)
        yield s


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float | None:
    for key, (p_in, p_out) in PRICES.items():
        if key in model.lower():
            return round((tokens_in * p_in + tokens_out * p_out) / 1e6, 6)
    return None


class TracedBackend:
    """Wraps any model backend: every call becomes an LLM span with model, tokens, cost and latency."""

    def __init__(self, inner, backend_name: str):
        self.inner = inner
        self.backend_name = backend_name

    def complete(self, system: str, prompt: str, schema: dict, model: str | None = None, images=None):
        kwargs = {"images": images} if images else {}
        if model:
            kwargs["model"] = model
        with span("llm", "LLM", **{"gen_ai.system": "anthropic", "gen_ai.operation.name": "chat",
                                   "lpa.backend": self.backend_name, "lpa.prompt_chars": len(prompt),
                                   "lpa.images": len(images or [])}) as s:
            res = self.inner.complete(system, prompt, schema, **kwargs)
            s.set_attribute("gen_ai.request.model", res.model)
            s.set_attribute("gen_ai.usage.input_tokens", res.input_tokens)
            s.set_attribute("gen_ai.usage.output_tokens", res.output_tokens)
            s.set_attribute("lpa.model_seconds", round(res.latency_s, 2))
            cost = cost_usd(res.model, res.input_tokens, res.output_tokens)
            if cost is not None:
                s.set_attribute("lpa.cost_usd", cost)
            return res
