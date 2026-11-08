"""Chaos switch: deliberately break a portal to test whether the agent recovers or hands off to a human.

Modes (any combination, per portal):
  layout_variant   buttons/links renamed and columns reordered (a portal redesign)
  renamed_fields   column headers renamed ("Invoice No." -> "Document #")
  session_expiry   the session dies right after the first PDF download
  slow             every page waits 2-4 s before answering
  captcha          login shows a CAPTCHA that cannot be solved -> the only right move is a human handoff

Set at startup with PORTAL_CHAOS="a:slow,captcha;b:layout_variant", or at runtime through
POST /admin/chaos (header X-Admin-Token) so an eval run can switch modes between tasks.
"""

from __future__ import annotations

import os

MODES = {"layout_variant", "renamed_fields", "session_expiry", "slow", "captcha"}
_state: dict[str, set[str]] = {"a": set(), "b": set(), "c": set()}


def _load_env() -> None:
    raw = os.environ.get("PORTAL_CHAOS", "")
    for part in filter(None, (p.strip() for p in raw.split(";"))):
        portal, _, modes = part.partition(":")
        set_modes(portal, [m for m in modes.split(",") if m])


def set_modes(portal: str, modes: list[str]) -> set[str]:
    if portal not in _state:
        raise ValueError(f"unknown portal {portal!r}")
    unknown = set(modes) - MODES
    if unknown:
        raise ValueError(f"unknown chaos modes {sorted(unknown)}; valid: {sorted(MODES)}")
    _state[portal] = set(modes)
    return _state[portal]


def active(portal: str, mode: str) -> bool:
    return mode in _state[portal]


def snapshot() -> dict[str, list[str]]:
    return {p: sorted(m) for p, m in _state.items()}


_load_env()
