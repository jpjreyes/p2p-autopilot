"""Weekly brief (D19): code computes the numbers, the model only writes, invented numbers are caught."""

from datetime import date

import pytest

from legacy_portal.process import grounding
from legacy_portal.process.brief import brief
from legacy_portal.process.warehouse import DEFAULT_DB

needs_warehouse = pytest.mark.skipif(not DEFAULT_DB.exists(), reason="warehouse not built")


class Fake:
    """A backend that writes a fixed summary; the first one invents a number, the retry doesn't."""

    def __init__(self, texts):
        self.texts, self.calls = list(texts), []

    def complete(self, system, prompt, schema, model=None):
        self.calls.append(prompt)
        return type("R", (), {"data": {"headline": "Week", "bullets": [self.texts.pop(0)]}})()


def test_grounding_rejects_a_number_no_analysis_produced():
    results = {"open_long": [[828, 1015808.0, 122.0]]}
    nums = grounding.check("EUR 1,015,808 on 828 lines, median 122 days; 9,999 more expected", results)
    assert [n.text for n in nums if n.status == "ungrounded"] == ["9,999"]


@needs_warehouse
def test_latest_brief_reproduces_the_p2_headline_numbers():
    b = brief(use_llm=False)
    open_long = dict(zip(b["sections"]["open_long"]["columns"], b["sections"]["open_long"]["rows"][0]))
    assert (open_long["lines"], open_long["eur"]) == (828, 1015808.0)  # Process Copilot's "open longer than usual"
    assert "block_risk" in b["sections"]  # the model's worklist only appears in the latest week


@needs_warehouse
def test_older_weeks_have_no_model_section_and_the_retry_removes_invented_numbers(monkeypatch):
    from legacy_portal.process import brief as mod
    fake = Fake(["Paid 99,999 before receipt [paid_early]", "Nothing unusual this week [week]"])
    monkeypatch.setattr("legacy_portal.llm.get_backend", lambda: fake)
    b = mod.brief(date(2018, 10, 1))
    assert "block_risk" not in b["sections"]
    assert len(fake.calls) == 2 and "99,999" in fake.calls[1]  # the retry names the invented number
    assert b["unverified_numbers"] == []
