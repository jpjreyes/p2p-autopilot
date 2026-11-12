"""Tracing: model calls become LLM spans with tokens and cost, the match is a span with its verdict, and no prompt
or invoice text ends up in the trace."""

import json
from decimal import Decimal

import pytest

from p2p_autopilot.llm import LLMResult


@pytest.fixture(scope="module")
def exporter():
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    trace.set_tracer_provider(provider)
    return exp


class FakeModel:
    def complete(self, system, prompt, schema, model=None, images=None):
        return LLMResult({"ok": True}, 1200, 80, 0.5, "claude-haiku-5-5")


def test_model_call_span_has_tokens_and_cost_but_no_prompt(exporter):
    from p2p_autopilot.tracing import TracedBackend
    exporter.clear()
    secret = "Invoice INV-1059 for EUR 2,014.75, password hunter2"
    TracedBackend(FakeModel(), "fake").complete("system", secret, {})
    (s,) = [s for s in exporter.get_finished_spans() if s.name == "llm"]
    a = dict(s.attributes)
    assert a["gen_ai.usage.input_tokens"] == 1200 and a["gen_ai.usage.output_tokens"] == 80
    assert a["lpa.cost_usd"] == pytest.approx((1200 * 0.10 + 80 * 0.50) / 1e6)
    assert a["openinference.span.kind"] == "LLM"
    assert "hunter2" not in json.dumps(a) and "2,014.75" not in json.dumps(a)


def test_match_span_carries_the_verdict(exporter):
    from p2p_autopilot import tracing
    from p2p_autopilot.matching import DocLine, ExtractedDoc, Ledger, match

    class Orders:
        def get_po(self, n):
            return None

        def received_qty(self, n):
            return {}

        def is_paid(self, s, n):
            return False

    exporter.clear()
    doc = ExtractedDoc("SUP-ACME", "INV-1", "invoice", "PO-49000001", "2018-10-01", Decimal("10.00"),
                       (DocLine("ITEM-00010", 1, Decimal("10.00")),))
    with tracing.span("match", "TOOL", **{"lpa.number": doc.number}) as sp:
        v = match(doc, Orders(), Ledger())
        sp.set_attribute("lpa.verdict", v.verdict)
    (s,) = [s for s in exporter.get_finished_spans() if s.name == "match"]
    assert s.attributes["lpa.verdict"] == "unknown_po"
