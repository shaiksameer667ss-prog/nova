"""Structured planning and bounded plan revision for NOVA."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from nova.controller.contracts import ACTION_CONTRACTS


def available_action_capabilities() -> list[dict[str, Any]]:
    """Return actual controller actions and their declared capabilities."""
    capabilities = []
    for name, contract in ACTION_CONTRACTS.items():
        if not contract.description:
            raise RuntimeError(f"Action {name!r} has no description.")
        capabilities.append({
            "action": name,
            "description": contract.description,
            "required_arguments": sorted(contract.required_fields),
            "optional_arguments": sorted(contract.optional_fields),
            "effect": contract.effect,
        })
    return capabilities


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "objective": {
            "type": "string",
            "minLength": 1,
            "maxLength": 500,
        },
        "steps": {
            "type": "array",
            "minItems": 2,
            "maxItems": 8,
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 500,
            },
        },
        "success_criteria": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 500,
            },
        },
        "risks": {
            "type": "array",
            "minItems": 0,
            "maxItems": 5,
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 500,
            },
        },
        "change_summary": {
            "type": "string",
            "minLength": 1,
            "maxLength": 300,
        },
    },
    "required": [
        "objective",
        "steps",
        "success_criteria",
        "risks",
        "change_summary",
    ],
    "additionalProperties": False,
}

PLAN_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "nova_execution_plan",
        "schema": PLAN_SCHEMA,
    },
}

PLAN_SYSTEM_PROMPT = """You are NOVA's planning module.

Analyze the task and produce a concise, executable plan.
Do not solve the task or claim that any work has been completed.

Requirements:
- State the actual objective.
- Create 2 to 8 ordered, concrete steps.
- Define 1 to 6 observable success criteria.
- Identify up to 5 relevant risks or uncertainties.
- Keep steps specific enough to guide tool selection.
- Do not invent files, tools, results, or capabilities.
- Use only actions and arguments listed in available_actions.
- Never invent commands, flags, parameters, or fallback tools.
- Treat action descriptions as authoritative capability limits.
- Return JSON only, matching the supplied schema.
- Set change_summary to "Initial plan".
"""

REPLAN_SYSTEM_PROMPT = """You are NOVA's adaptive planning module.

The current strategy encountered a failure.
Analyze the task, current plan, failed action, and actual observation.

Produce a revised plan that:
- Preserves the original objective.
- Uses the failure as evidence.
- Compare the failure with actual available action descriptions.
- Distinguish transient failures from unsupported operations.
- Retrying an action may be appropriate after a transient failure.
- Never claim a fallback mechanism unless an available action supports it.
- Avoids repeating the same ineffective approach without justification.
- Retains useful steps where appropriate.
- Changes the strategy when necessary.
- Defines observable success criteria.
- Does not claim that any task work has been completed.
- Explains the revision in change_summary.
- Keeps change_summary concise and within 300 characters.
- Returns JSON only, matching the supplied schema.
"""


class PlanValidationError(ValueError):
    """Raised when a model-generated plan violates the planning contract."""


def validate_plan(value: Any) -> dict:
    """Validate and normalize a model-generated plan."""
    if not isinstance(value, dict):
        raise PlanValidationError("Plan must be a JSON object.")

    required = {
        "objective",
        "steps",
        "success_criteria",
        "risks",
        "change_summary",
    }
    if set(value) != required:
        missing = sorted(required - set(value))
        extra = sorted(set(value) - required)
        raise PlanValidationError(
            f"Invalid plan fields; missing={missing}, unexpected={extra}"
        )

    def check_text(field: str, maximum: int) -> str:
        text = value[field]
        if not isinstance(text, str):
            raise PlanValidationError(f"{field} must be a string.")
        text = text.strip()
        if not text:
            raise PlanValidationError(f"{field} must not be empty.")
        if len(text) > maximum:
            raise PlanValidationError(f"{field} exceeds {maximum} characters.")
        return text

    objective = check_text("objective", 500)
    change_summary = check_text("change_summary", 300)

    def check_list(field: str, minimum: int, maximum: int) -> list[str]:
        items = value[field]
        if not isinstance(items, list):
            raise PlanValidationError(f"{field} must be a list.")
        if not minimum <= len(items) <= maximum:
            raise PlanValidationError(
                f"{field} must contain between {minimum} and {maximum} items."
            )

        result = []
        for index, item in enumerate(items):
            if not isinstance(item, str):
                raise PlanValidationError(
                    f"{field}[{index}] must be a string."
                )
            item = item.strip()
            if not item:
                raise PlanValidationError(
                    f"{field}[{index}] must not be empty."
                )
            if len(item) > 500:
                raise PlanValidationError(
                    f"{field}[{index}] exceeds 500 characters."
                )
            result.append(item)
        return result

    return {
        "objective": objective,
        "steps": check_list("steps", 2, 8),
        "success_criteria": check_list("success_criteria", 1, 6),
        "risks": check_list("risks", 0, 5),
        "change_summary": change_summary,
    }


def parse_plan(response: str) -> dict:
    """Parse and validate a JSON plan returned by the model."""
    if not isinstance(response, str):
        raise PlanValidationError("Model plan response must be a string.")

    text = response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or not lines[-1].strip().startswith("```"):
            raise PlanValidationError("Incomplete JSON code fence.")
        text = "\n".join(lines[1:-1]).strip()

    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanValidationError(
            f"Model returned invalid plan JSON: {exc}"
        ) from exc

    return validate_plan(value)


def create_plan_record(plan: dict) -> dict:
    """Create a durable record of the initial plan."""
    normalized = validate_plan(plan)
    return {
        "schema_version": 1,
        "initial": deepcopy(normalized),
        "current": deepcopy(normalized),
        "revisions": [],
    }


def add_plan_revision(record: dict, revised_plan: dict) -> dict:
    """Append a validated revision without overwriting planning history."""
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise PlanValidationError("Invalid plan record.")

    normalized = validate_plan(revised_plan)
    updated = deepcopy(record)
    revision_number = len(updated["revisions"]) + 1

    updated["revisions"].append({
        "revision": revision_number,
        "plan": deepcopy(normalized),
    })
    updated["current"] = deepcopy(normalized)
    return updated


def build_initial_plan_messages(task: str) -> list[dict[str, str]]:
    if not isinstance(task, str) or not task.strip():
        raise ValueError("Task must not be empty.")

    context = {
        "task": task,
        "available_actions": available_action_capabilities(),
    }
    return [
        {"role": "system", "content": PLAN_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Create an execution plan using only these actual actions "
                "and arguments:\n"
                + json.dumps(context, ensure_ascii=False, indent=2)
            ),
        },
    ]


def build_replan_messages(
    task: str,
    record: dict,
    failed_action: dict,
    observation: str,
) -> list[dict[str, str]]:
    """Build a focused replan request using the latest failure evidence."""
    if not isinstance(observation, str):
        raise TypeError("Failure observation must be a string.")

    context = {
        "task": task,
        "current_plan": record["current"],
        "failed_action": failed_action,
        "failure_observation": observation[:4000],
        "available_actions": available_action_capabilities(),
    }

    return [
        {"role": "system", "content": REPLAN_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(context, ensure_ascii=False),
        },
    ]


def render_plan_context(record: dict) -> str:
    """Render the current plan and actual capabilities for the action model."""
    revision_count = len(record["revisions"])
    return (
        f"Current execution plan (revision {revision_count}):\\n"
        f"{json.dumps(record['current'], ensure_ascii=False, indent=2)}\\n"
        "Actual available action capabilities:\\n"
        f"{json.dumps(available_action_capabilities(), ensure_ascii=False, indent=2)}\\n"
        "Use only these actions and declared arguments. Do not invent tools, "
        "flags, or fallback mechanisms. Adapt when observations show that "
        "the strategy is ineffective. A plan is not proof of success."
    )
