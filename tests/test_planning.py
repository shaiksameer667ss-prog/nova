import json

import pytest

from nova.controller.planning import (
    PlanValidationError,
    add_plan_revision,
    build_initial_plan_messages,
    build_replan_messages,
    create_plan_record,
    parse_plan,
    render_plan_context,
    validate_plan,
)


def valid_plan(**overrides):
    plan = {
        "objective": "Correct the inventory commit behavior.",
        "steps": [
            "Inspect the ledger implementation.",
            "Identify why repeated commits reapply adjustments.",
            "Correct the commit behavior.",
        ],
        "success_criteria": [
            "Each staged adjustment is applied exactly once.",
        ],
        "risks": ["A change could break staging after a commit."],
        "change_summary": "Initial plan",
    }
    plan.update(overrides)
    return plan


def test_validate_plan_accepts_valid_plan():
    result = validate_plan(valid_plan())
    assert result["objective"] == "Correct the inventory commit behavior."
    assert len(result["steps"]) == 3


def test_parse_plan_accepts_json():
    raw = json.dumps(valid_plan())
    assert parse_plan(raw) == valid_plan()


@pytest.mark.parametrize(
    ("task", "step", "message"),
    [
        (
            "Fix the parser. Do not execute tests.",
            "Run pytest and confirm the tests pass.",
            "prohibited test execution",
        ),
        (
            "Fix the parser. Do not modify or execute tests.",
            "Update the test files to match the new behavior.",
            "prohibited test modification",
        ),
        (
            "Fix the parser. Do not inspect tests.",
            "Inspect the hidden tests for expected behavior.",
            "prohibited test read",
        ),
    ],
)
def test_parse_plan_rejects_explicitly_prohibited_test_actions(
    task, step, message
):
    plan = valid_plan(steps=[
        "Inspect the parser implementation.",
        step,
    ])
    with pytest.raises(PlanValidationError, match=message):
        parse_plan(json.dumps(plan), task=task)


def test_parse_plan_allows_read_only_inspection_when_not_prohibited():
    task = "Fix the parser. Do not modify or execute tests."
    plan = valid_plan(steps=[
        "Inspect the parser implementation.",
        "Read the test file without modifying or executing it.",
    ])
    assert parse_plan(json.dumps(plan), task=task) == plan


def test_plan_prompts_preserve_explicit_task_constraints():
    task = "Fix the parser. Do not modify or execute tests."
    initial = build_initial_plan_messages(task)

    assert "every explicit task prohibition" in initial[0]["content"]
    assert "read-only inspection" in initial[0]["content"]

    revised = build_replan_messages(
        task,
        create_plan_record(valid_plan()),
        {"action": "read_file", "path": "parser.py"},
        "Observed parser behavior.",
    )
    assert "every explicit task prohibition" in revised[0]["content"]


def test_parse_plan_accepts_json_code_fence():
    raw = "```json\n" + json.dumps(valid_plan()) + "\n```"
    assert parse_plan(raw) == valid_plan()


def test_parse_plan_rejects_invalid_json():
    with pytest.raises(PlanValidationError, match="invalid plan JSON"):
        parse_plan("{not json}")


def test_parse_plan_rejects_non_string_response():
    with pytest.raises(PlanValidationError, match="must be a string"):
        parse_plan(None)


def test_validate_plan_rejects_non_object():
    with pytest.raises(PlanValidationError, match="JSON object"):
        validate_plan([])


def test_validate_plan_rejects_missing_fields():
    plan = valid_plan()
    del plan["steps"]
    with pytest.raises(PlanValidationError, match="missing"):
        validate_plan(plan)


def test_validate_plan_rejects_unexpected_fields():
    plan = valid_plan(extra="not allowed")
    with pytest.raises(PlanValidationError, match="unexpected"):
        validate_plan(plan)


@pytest.mark.parametrize(
    "steps",
    [[], ["Only one step"], [""] * 9],
)
def test_validate_plan_enforces_step_count(steps):
    with pytest.raises(PlanValidationError, match="steps must contain"):
        validate_plan(valid_plan(steps=steps))


def test_validate_plan_rejects_empty_success_criteria():
    with pytest.raises(PlanValidationError, match="success_criteria must contain"):
        validate_plan(valid_plan(success_criteria=[]))


def test_validate_plan_rejects_non_string_step():
    with pytest.raises(PlanValidationError, match=r"steps\[1\] must be a string"):
        validate_plan(valid_plan(steps=["Inspect implementation", 42]))


def test_validate_plan_rejects_blank_objective():
    with pytest.raises(PlanValidationError, match="objective must not be empty"):
        validate_plan(valid_plan(objective="  "))


def test_validate_plan_rejects_oversized_field():
    with pytest.raises(PlanValidationError, match="objective exceeds"):
        validate_plan(valid_plan(objective="x" * 501))


def test_create_plan_record_preserves_initial_plan():
    initial = valid_plan()
    record = create_plan_record(initial)

    assert record["schema_version"] == 1
    assert record["initial"] == initial
    assert record["current"] == initial
    assert record["revisions"] == []


def test_add_revision_preserves_history():
    initial = create_plan_record(valid_plan())
    revised = valid_plan(
        steps=[
            "Inspect the failing commit behavior.",
            "Clear staged adjustments after successful application.",
        ],
        change_summary="Changed the fix strategy after observing repeated application.",
    )

    updated = add_plan_revision(initial, revised)

    assert updated["current"] == revised
    assert updated["initial"] == initial["initial"]
    assert updated["revisions"][0]["revision"] == 1
    assert updated["revisions"][0]["plan"] == revised
    assert initial["revisions"] == []


def test_revision_numbers_are_sequential():
    record = create_plan_record(valid_plan())
    first = valid_plan(change_summary="First revision")
    second = valid_plan(change_summary="Second revision")

    record = add_plan_revision(record, first)
    record = add_plan_revision(record, second)

    assert [item["revision"] for item in record["revisions"]] == [1, 2]


def test_initial_plan_messages_include_task():
    messages = build_initial_plan_messages("Fix inventory ledger.")

    assert messages[0]["role"] == "system"
    assert "Fix inventory ledger." in messages[1]["content"]


def test_replan_messages_include_failure_evidence():
    record = create_plan_record(valid_plan())
    messages = build_replan_messages(
        "Fix inventory ledger.",
        record,
        {"action": "write_file", "path": "ledger.py"},
        "Permission denied",
    )

    content = messages[1]["content"]
    assert "Permission denied" in content
    assert "write_file" in content
    assert "current_plan" in content


def test_replan_observation_is_bounded():
    record = create_plan_record(valid_plan())
    messages = build_replan_messages(
        "Task",
        record,
        {"action": "read_file", "path": "ledger.py"},
        "x" * 10000,
    )
    data = json.loads(messages[1]["content"])
    assert len(data["failure_observation"]) == 4000


def test_render_plan_context_identifies_revision():
    record = create_plan_record(valid_plan())
    record = add_plan_revision(
        record,
        valid_plan(change_summary="Revised after failure."),
    )

    context = render_plan_context(record)
    assert "revision 1" in context
    assert "not proof of success" in context

def test_replan_rejects_non_string_observation():
    record = create_plan_record(valid_plan())
    with pytest.raises(TypeError, match="must be a string"):
        build_replan_messages("Task", record, {"action": "read_file"}, None)


def test_initial_plan_includes_actual_controller_capabilities():
    import json

    from nova.controller.contracts import ACTION_CONTRACTS

    messages = build_initial_plan_messages("Inspect and update a file.")
    message = messages[1]["content"]
    instruction, separator, payload = message.partition(chr(10))
    assert separator
    assert "actual actions" in instruction
    context = json.loads(payload)
    capabilities = {
        item["action"]: item for item in context["available_actions"]
    }

    assert context["task"] == "Inspect and update a file."
    assert set(capabilities) == set(ACTION_CONTRACTS)
    assert capabilities["write_file"]["required_arguments"] == [
        "content", "path"
    ]
    assert "Does not append a newline" in (
        capabilities["write_file"]["description"]
    )
    assert capabilities["read_file"]["required_arguments"] == ["path"]
    assert capabilities["list_files"]["optional_arguments"] == ["subdir"]
    assert capabilities["done"]["required_arguments"] == ["summary"]


def test_replan_includes_actual_capabilities_and_failure_evidence():
    import json

    record = create_plan_record(valid_plan())
    messages = build_replan_messages(
        "Complete the task.",
        record,
        {"action": "write_file", "path": "answer.txt", "content": "test"},
        "OSError: transient write failure",
    )
    context = json.loads(messages[1]["content"])

    assert context["task"] == "Complete the task."
    assert "transient write failure" in context["failure_observation"]
    assert {
        item["action"] for item in context["available_actions"]
    } == {"write_file", "read_file", "list_files", "done"}


def test_rendered_plan_context_includes_action_capabilities():
    record = create_plan_record(valid_plan())
    rendered = render_plan_context(record)

    assert "Actual available action capabilities" in rendered
    assert "write_file" in rendered
    assert "read_file" in rendered
    assert "list_files" in rendered

@pytest.mark.parametrize(
    "criterion",
    [
        "No test files are modified or executed.",
        "Test files must not be modified or executed.",
        "Tests should not be modified or run.",
        "Tests are not modified or executed.",
        "Modify the implementation without changing tests.",
        "Do not modify or execute tests.",
    ],
)
def test_parse_plan_accepts_non_prohibited_test_constraints(criterion):
    task = "Fix the parser. Do not modify or execute tests."
    plan = valid_plan(success_criteria=[criterion])

    assert parse_plan(json.dumps(plan), task=task) == plan

