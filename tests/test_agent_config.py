"""Ablation variants (D13) must change only what they claim to, and the defaults must be the production agent."""

from legacy_portal.agent import ACTION_SCHEMA, MAX_BATCH, SYSTEM, configure


def actions(schema):
    return schema["properties"]["actions"]["items"]["properties"]["action"]["enum"]


def test_defaults_are_production():
    system, schema = configure()
    assert system == SYSTEM and schema == ACTION_SCHEMA and schema["properties"]["actions"]["maxItems"] == MAX_BATCH


def test_no_look_removes_the_capability_not_just_the_words():
    system, schema = configure(allow_look=False)
    assert "look" not in actions(schema) and "mark" not in schema["properties"]["actions"]["items"]["properties"]
    assert "screenshot" not in system and '"mark"' not in system
    assert "look" in actions(ACTION_SCHEMA)  # the production schema is untouched


def test_batch1_allows_one_action():
    system, schema = configure(max_batch=1)
    assert schema["properties"]["actions"]["maxItems"] == 1
    assert "exactly one action" in system and "batch up to" not in system
