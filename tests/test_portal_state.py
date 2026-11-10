"""Portal state shared through Postgres (D5): two instances, as two Lambdas would be, see one state.
Skipped when DATABASE_URL is not set (scripts/dev_db.sh up)."""

import os

import pytest

from legacy_portal.portals.chaos import PostgresState

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL")


def test_two_instances_share_modes_one_shots_and_side_effects():
    one, two = PostgresState(os.environ["DATABASE_URL"]), PostgresState(os.environ["DATABASE_URL"])
    one.set_modes("d", ["session_expiry", "slow"])
    two.cache.clear()
    assert two.get_modes("d") == {"session_expiry", "slow"}
    assert [one.fire_once("d", "session_expiry"), two.fire_once("d", "session_expiry")].count(True) == 1
    two.record("d", "paper copy mailed for X")
    assert one.effects_of("d") == ["paper copy mailed for X"]
    one.set_modes("d", [])  # reset clears modes, one-shots and side effects
    two.cache.clear()
    assert two.get_modes("d") == set() and two.effects_of("d") == []
