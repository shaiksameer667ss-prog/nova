from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

ActionEffect = Literal["read", "write", "control"]


@dataclass(frozen=True)
class ActionContract:
    """Declarative contract for one NOVA controller action."""

    required_fields: frozenset[str]
    optional_fields: frozenset[str]
    non_empty_fields: frozenset[str]
    effect: ActionEffect
    description: str = ""


ACTION_CONTRACTS = MappingProxyType({
    "write_file": ActionContract(
        required_fields=frozenset({"path", "content"}),
        optional_fields=frozenset(),
        non_empty_fields=frozenset({"path"}),
        effect="write",
        description=(
            "Writes supplied content exactly as UTF-8 bytes. "
            "Does not append a newline. Creates parent directories, "
            "writes atomically, and avoids rewriting identical content."
        ),
    ),
    "read_file": ActionContract(
        required_fields=frozenset({"path"}),
        optional_fields=frozenset(),
        non_empty_fields=frozenset({"path"}),
        effect="read",
        description=(
            "Reads an existing workspace file as UTF-8 text."
        ),
    ),
    "list_files": ActionContract(
        required_fields=frozenset(),
        optional_fields=frozenset({"subdir"}),
        non_empty_fields=frozenset({"subdir"}),
        effect="read",
        description=(
            "Lists workspace files recursively in sorted order. "
            "An optional subdir selects the directory. "
            "A missing directory returns an empty result."
        ),
    ),
    "done": ActionContract(
        required_fields=frozenset({"summary"}),
        optional_fields=frozenset(),
        non_empty_fields=frozenset({"summary"}),
        effect="control",
        description=(
            "Ends the task with a summary. Does not independently "
            "inspect or verify task results."
        ),
    ),
})


def get_action_contract(action_name: str) -> ActionContract:
    """Return the contract for an action or raise ValueError."""
    contract = ACTION_CONTRACTS.get(action_name)
    if contract is None:
        raise ValueError(f"Unknown action: {action_name!r}")
    return contract


def validate_action(action: object) -> dict:
    """Validate the structure and arguments of a parsed NOVA action."""
    if not isinstance(action, dict):
        raise ValueError("Action must be a JSON object.")  # noqa: TRY004 - uniform action-validation error

    kind = action.get("action")
    if not isinstance(kind, str) or kind not in ACTION_CONTRACTS:
        raise ValueError(f"Unknown or missing action: {kind!r}")

    contract = ACTION_CONTRACTS[kind]
    allowed_fields = (
        {"action"}
        | contract.required_fields
        | contract.optional_fields
    )

    missing = contract.required_fields - set(action)
    unexpected = set(action) - allowed_fields

    if missing:
        raise ValueError(f"Missing required fields: {sorted(missing)}")

    if unexpected:
        raise ValueError(f"Unexpected fields: {sorted(unexpected)}")

    supplied_fields = contract.required_fields | (
        contract.optional_fields & set(action)
    )

    for field in supplied_fields:
        if not isinstance(action[field], str):
            raise ValueError(f"Field {field!r} must be a string.")  # noqa: TRY004 - uniform action-validation error

    for field in contract.non_empty_fields:
        if field in action and not action[field].strip():
            raise ValueError(f"Field {field!r} must not be empty.")

    return action
