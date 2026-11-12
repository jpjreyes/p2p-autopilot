"""The CLI runner's guarantees, with a fake `claude` process (no model calls, no usage)."""

import json
import subprocess

import pytest

from legacy_portal import llm, subscription


def fake_cli(monkeypatch, events, returncode=0, seen=None):
    def run(cmd, **kw):
        if seen is not None:
            seen.update(cmd=cmd, env=kw["env"], cwd=kw["cwd"])
        out = "\n".join(json.dumps(e) for e in events)
        return subprocess.CompletedProcess(cmd, returncode, out, "")
    monkeypatch.setattr(subscription.subprocess, "run", run)


def init(source="none"):
    return {"type": "system", "subtype": "init", "apiKeySource": source}


def limits(five=0.1, week=0.1, status="allowed"):
    return {"type": "rate_limit_event", "rate_limit_info": {"status": status, "unifiedWindows": {
        "five_hour": {"utilization": five}, "seven_day": {"utilization": week}}}}


def result(data):
    return {"type": "result", "is_error": False, "structured_output": data, "total_cost_usd": 0.0012,
            "usage": {"input_tokens": 10, "output_tokens": 5}}


@pytest.fixture(autouse=True)
def clean_setup(tmp_path, monkeypatch):
    token, config = tmp_path / "oauth_token", tmp_path / "config"
    token.write_text("tok-123\n")
    config.mkdir()
    monkeypatch.setattr(subscription, "TOKEN", token)
    monkeypatch.setattr(subscription, "CONFIG", config)
    monkeypatch.setattr(subscription, "last_limits", None)
    monkeypatch.delenv("CLAUDE_EVAL_ALLOW_DIRTY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-never-be-passed")
    return config


def test_clean_env_uses_token_and_empty_config_and_drops_api_key(monkeypatch, clean_setup):
    seen = {}
    fake_cli(monkeypatch, [init(), limits(), result({"ok": True})], seen=seen)
    r = llm.ClaudeCLIBackend().complete("sys", "hi", {"type": "object"}, model="haiku")
    assert r.data == {"ok": True} and r.cost_usd == 0.0012
    assert "ANTHROPIC_API_KEY" not in seen["env"]
    assert seen["env"]["CLAUDE_CONFIG_DIR"] == str(clean_setup)
    assert seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-123"
    assert seen["cwd"] != "/tmp" and "claude-eval-" in seen["cwd"]
    cmd = seen["cmd"]
    assert cmd[cmd.index("--model") + 1] == "claude-haiku-5-5"
    assert cmd[cmd.index("--effort") + 1] == "medium"  # the API's default for Haiku 5.5


def test_missing_setup_stops_unless_dirty_allowed(monkeypatch, tmp_path):
    monkeypatch.setattr(subscription, "TOKEN", tmp_path / "nope")
    fake_cli(monkeypatch, [init(), result({"ok": True})])
    with pytest.raises(subscription.NotClean):
        llm.ClaudeCLIBackend().complete("s", "p", {})
    monkeypatch.setenv("CLAUDE_EVAL_ALLOW_DIRTY", "1")
    assert llm.ClaudeCLIBackend().complete("s", "p", {}).data == {"ok": True}


def test_api_key_billing_is_refused(monkeypatch):
    fake_cli(monkeypatch, [init("ANTHROPIC_API_KEY"), result({"ok": True})])
    with pytest.raises(subscription.NotClean):
        llm.ClaudeCLIBackend().complete("s", "p", {})


def test_hook_means_not_clean(monkeypatch):
    fake_cli(monkeypatch, [init(), {"type": "system", "subtype": "hook_started"}, result({"ok": True})])
    with pytest.raises(subscription.NotClean):
        llm.ClaudeCLIBackend().complete("s", "p", {})


def test_usage_at_80_percent_stops_the_next_call(monkeypatch):
    fake_cli(monkeypatch, [init(), limits(week=0.81), result({"ok": True})])
    b = llm.ClaudeCLIBackend()
    assert b.complete("s", "p", {}).data == {"ok": True}  # this answer is kept
    with pytest.raises(subscription.QuotaStop):
        b.complete("s", "p", {})


def test_rejected_limit_stops_immediately(monkeypatch):
    fake_cli(monkeypatch, [init(), limits(status="rejected"), result({"ok": True})])
    with pytest.raises(subscription.QuotaStop):
        llm.ClaudeCLIBackend().complete("s", "p", {})


def test_stop_is_not_swallowed_by_broad_handlers(monkeypatch):
    fake_cli(monkeypatch, [init("ANTHROPIC_API_KEY")])
    with pytest.raises(subscription.EvalStop):
        try:
            llm.ClaudeCLIBackend().complete("s", "p", {})
        except Exception:  # what a task-level retry loop would do
            pytest.fail("EvalStop must not be an Exception")


def test_extra_usage_stops_immediately(monkeypatch):
    ev = limits()
    ev["rate_limit_info"]["isUsingOverage"] = True
    fake_cli(monkeypatch, [init(), ev, result({"ok": True})])
    with pytest.raises(subscription.QuotaStop):
        llm.ClaudeCLIBackend().complete("s", "p", {})


def test_api_key_in_token_file_is_refused(monkeypatch, tmp_path):
    bad = tmp_path / "bad_token"
    bad.write_text("sk-ant-api03-xxxx")
    monkeypatch.setattr(subscription, "TOKEN", bad)
    fake_cli(monkeypatch, [init(), result({"ok": True})])
    with pytest.raises(subscription.NotClean):
        llm.ClaudeCLIBackend().complete("s", "p", {})
