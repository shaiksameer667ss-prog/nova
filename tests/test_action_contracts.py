from dataclasses import FrozenInstanceError

import pytest

from nova.controller.contracts import (
    ACTION_CONTRACTS,
    get_action_contract,
    validate_action,
)


@pytest.mark.parametrize(
    ("action", "effect"),
    [
        ({"action": "write_file", "path": "a.py", "content": "x"}, "write"),
        ({"action": "read_file", "path": "a.py"}, "read"),
        ({"action": "list_files"}, "read"),
        ({"action": "done", "summary": "finished"}, "control"),
    ],
)
def test_valid_actions_and_effects(action, effect):
    validated = validate_action(action)
    assert validated == action
    assert get_action_contract(action["action"]).effect == effect


@pytest.mark.parametrize("action", [None, [], "invalid", 42])
def test_rejects_non_object_actions(action):
    with pytest.raises(ValueError, match="JSON object"):
        validate_action(action)


def test_rejects_unknown_action():
    with pytest.raises(ValueError, match="Unknown or missing action"):
        validate_action({"action": "delete_file"})


@pytest.mark.parametrize(
    "action",
    [
        {"action": "write_file", "path": "a.py"},
        {"action": "write_file", "content": "x"},
        {"action": "read_file"},
        {"action": "done"},
    ],
)
def test_rejects_missing_required_fields(action):
    with pytest.raises(ValueError, match="Missing required fields"):
        validate_action(action)


@pytest.mark.parametrize(
    "action",
    [
        {"action": "read_file", "path": "a.py", "content": "extra"},
        {"action": "done", "summary": "ok", "path": "extra"},
        {"action": "list_files", "unknown": "extra"},
    ],
)
def test_rejects_unexpected_fields(action):
    with pytest.raises(ValueError, match="Unexpected fields"):
        validate_action(action)


@pytest.mark.parametrize(
    "action",
    [
        {"action": "read_file", "path": 123},
        {"action": "write_file", "path": "a.py", "content": 123},
        {"action": "list_files", "subdir": 123},
        {"action": "done", "summary": 123},
    ],
)
def test_rejects_wrong_field_types(action):
    with pytest.raises(ValueError, match="must be a string"):
        validate_action(action)


@pytest.mark.parametrize(
    "action",
    [
        {"action": "read_file", "path": ""},
        {"action": "read_file", "path": "   "},
        {"action": "write_file", "path": "   ", "content": "x"},
        {"action": "done", "summary": "   "},
        {"action": "list_files", "subdir": ""},
    ],
)
def test_rejects_empty_required_values(action):
    with pytest.raises(ValueError, match="must not be empty"):
        validate_action(action)


def test_empty_file_content_is_allowed():
    action = {"action": "write_file", "path": "empty.txt", "content": ""}
    assert validate_action(action) == action


def test_all_contracts_have_valid_effect_metadata():
    assert set(ACTION_CONTRACTS) == {
        "write_file",
        "read_file",
        "list_files",
        "done",
    }
    assert all(
        contract.effect in {"read", "write", "control"}
        for contract in ACTION_CONTRACTS.values()
    )


def test_unknown_contract_is_rejected():
    with pytest.raises(ValueError, match="Unknown action"):
        get_action_contract("delete_file")


def test_contracts_are_immutable():
    contract = get_action_contract("read_file")
    with pytest.raises(FrozenInstanceError):
        contract.effect = "write"


def test_contract_definitions_use_frozen_sets():
    assert isinstance(
        get_action_contract("write_file").required_fields,
        frozenset,
    )



def test_action_registry_is_immutable():
    with pytest.raises(TypeError):
        ACTION_CONTRACTS["read_file"] = ACTION_CONTRACTS["write_file"]
