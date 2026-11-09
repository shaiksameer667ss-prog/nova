import pytest

from nova.controller.loop import (
    NOVA_ACTION_SCHEMA,
    NOVA_RESPONSE_FORMAT,
    _validate_action,
)


@pytest.mark.parametrize("action", [
    {"action": "write_file", "path": "a.py", "content": "print(1)"},
    {"action": "read_file", "path": "a.py"},
    {"action": "list_files"},
    {"action": "list_files", "subdir": "."},
    {"action": "done", "summary": "Completed."},
])
def test_validate_action_accepts_valid_actions(action):
    assert _validate_action(action) == action


@pytest.mark.parametrize("action", [
    None,
    [],
    {},
    {"action": "unknown"},
    {"action": "write_file", "path": "a.py"},
    {"action": "write_file", "content": "code"},
    {"action": "read_file"},
    {"action": "done"},
    {"action": "read_file", "path": "a.py", "content": "unexpected"},
    {"action": "write_file", "path": 123, "content": "code"},
    {"action": "list_files", "subdir": 123},
])
def test_validate_action_rejects_invalid_actions(action):
    with pytest.raises(ValueError):
        _validate_action(action)


def test_schema_allows_only_four_action_names():
    action_schema = NOVA_ACTION_SCHEMA["properties"]["action"]

    assert action_schema["enum"] == [
        "write_file", "read_file", "list_files", "done"
    ]
    assert NOVA_ACTION_SCHEMA["required"] == ["action"]
    assert NOVA_ACTION_SCHEMA["additionalProperties"] is False


def test_response_format_uses_nova_action_schema():
    assert NOVA_RESPONSE_FORMAT["type"] == "json_schema"
    assert NOVA_RESPONSE_FORMAT["json_schema"]["schema"] is NOVA_ACTION_SCHEMA
