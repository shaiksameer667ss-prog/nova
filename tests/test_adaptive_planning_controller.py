import json
import sqlite3
from unittest.mock import MagicMock, patch

from nova.config import Settings
from nova.controller.loop import NOVA_RESPONSE_FORMAT
from nova.controller.planning import PLAN_RESPONSE_FORMAT


def make_settings(tmp_path, max_steps=8):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return Settings(
        base_url="http://localhost:11434/v1",
        api_key="test",
        model="test-model",
        workspace=workspace,
        db=tmp_path / "test.db",
        max_steps=max_steps,
        temperature=0.2,
    )


def usage(prompt=10, completion=5):
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "usage_complete": True,
        "usage_json": "{}",
        "finish_reason": "stop",
    }


def plan(change="Initial plan"):
    return json.dumps({
        "objective": "Complete the requested task correctly.",
        "steps": [
            "Inspect the relevant files.",
            "Make the required change.",
            "Verify the resulting behavior.",
        ],
        "success_criteria": [
            "The requested behavior is correct.",
        ],
        "risks": [
            "The change may affect existing behavior.",
        ],
        "change_summary": change,
    })


def action(name, **fields):
    return json.dumps({"action": name, **fields})


def install_model(responses):
    mock_client = MagicMock()
    mock_client.chat_with_usage.side_effect = responses
    mock_client.close = MagicMock()
    return mock_client


def read_database(settings):
    conn = sqlite3.connect(settings.db)
    conn.row_factory = sqlite3.Row
    episodes = conn.execute(
        "SELECT * FROM episodes"
    ).fetchall()
    calls = conn.execute(
        "SELECT purpose, prompt_tokens, completion_tokens, total_tokens "
        "FROM model_calls ORDER BY rowid"
    ).fetchall()
    conn.close()
    return episodes, calls


def test_initial_plan_is_generated_and_persisted(tmp_path):
    settings = make_settings(tmp_path)
    fake_client = install_model([
        (plan(), usage(), "success"),
        (action("done", summary="Completed task"), usage(), "success"),
    ])

    with patch(
        "nova.controller.loop.ModelClient", return_value=fake_client
    ):
        from nova.controller.loop import run_task
        result = run_task("Complete the task", settings, planning_mode=True)

    assert result["agent_success"] is True
    assert result["planning_mode"] is True
    assert result["plan_revisions"] == 0
    assert result["stop_reason"] == "completed"

    episodes, calls = read_database(settings)
    stored_plan = json.loads(episodes[0]["plan"])

    assert stored_plan["schema_version"] == 1
    assert stored_plan["initial"]["change_summary"] == "Initial plan"
    assert stored_plan["current"] == stored_plan["initial"]
    assert stored_plan["revisions"] == []

    assert [row["purpose"] for row in calls] == [
        "planning",
        "agent_step",
    ]

    assert fake_client.chat_with_usage.call_args_list[0].kwargs[
        "response_format"
    ] == PLAN_RESPONSE_FORMAT

    assert fake_client.chat_with_usage.call_args_list[1].kwargs[
        "response_format"
    ] == NOVA_RESPONSE_FORMAT

    assert result["total_tokens"] == 30


def test_failed_action_triggers_replanning(tmp_path):
    settings = make_settings(tmp_path)
    revised = plan("Revised after observing the missing file.")

    fake_client = install_model([
        (plan(), usage(), "success"),
        (action("read_file", path="missing.py"), usage(), "success"),
        (revised, usage(), "success"),
        (action("done", summary="Recovered and completed"), usage(), "success"),
    ])

    with (
        patch("nova.controller.loop.ModelClient", return_value=fake_client),
        patch(
            "nova.controller.loop._dispatch",
            side_effect=FileNotFoundError("missing.py"),
        ),
    ):
        from nova.controller.loop import run_task
        result = run_task("Complete the task", settings, planning_mode=True)

    assert result["agent_success"] is True
    assert result["plan_revisions"] == 1

    episodes, calls = read_database(settings)
    stored_plan = json.loads(episodes[0]["plan"])

    assert len(stored_plan["revisions"]) == 1
    assert stored_plan["current"]["change_summary"] == (
        "Revised after observing the missing file."
    )
    assert [row["purpose"] for row in calls] == [
        "planning",
        "agent_step",
        "replanning",
        "agent_step",
    ]

    replan_messages = fake_client.chat_with_usage.call_args_list[2].args[0]
    assert "missing.py" in replan_messages[1]["content"]


def test_replanning_is_bounded_to_two_revisions(tmp_path):
    settings = make_settings(tmp_path, max_steps=8)

    responses = [
        (plan(), usage(), "success"),
        (
            action("read_file", path="one.py"),
            usage(),
            "success",
        ),
        (plan("Revision one"), usage(), "success"),
        (
            action("list_files"),
            usage(),
            "success",
        ),
        (plan("Revision two"), usage(), "success"),
        (
            action("write_file", path="result.py", content="x"),
            usage(),
            "success",
        ),
        (
            action("done", summary="Finished after bounded recovery"),
            usage(),
            "success",
        ),
    ]

    fake_client = install_model(responses)

    failures = [
        FileNotFoundError("missing one"),
        PermissionError("permission denied"),
        OSError("disk unavailable"),
    ]

    with (
        patch("nova.controller.loop.ModelClient", return_value=fake_client),
        patch(
            "nova.controller.loop._dispatch",
            side_effect=failures,
        ),
    ):
        from nova.controller.loop import run_task
        result = run_task("Complete the task", settings, planning_mode=True)

    assert result["agent_success"] is True
    assert result["plan_revisions"] == 2

    episodes, calls = read_database(settings)
    stored_plan = json.loads(episodes[0]["plan"])

    assert len(stored_plan["revisions"]) == 2
    assert sum(row["purpose"] == "replanning" for row in calls) == 2


def test_initial_planning_failure_stops_before_actions(tmp_path):
    settings = make_settings(tmp_path)
    failed_usage = {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "usage_complete": False,
        "usage_json": None,
        "finish_reason": None,
    }

    fake_client = install_model([
        ("", failed_usage, "error: planning service unavailable"),
    ])

    with patch(
        "nova.controller.loop.ModelClient", return_value=fake_client
    ):
        from nova.controller.loop import run_task
        result = run_task("Complete the task", settings, planning_mode=True)

    assert result["agent_success"] is False
    assert result["stop_reason"] == "planning_error"
    assert result["planning_error"] is not None
    assert result["total_tokens"] is None
    assert fake_client.chat_with_usage.call_count == 1

    episodes, calls = read_database(settings)

    assert episodes[0]["plan"] is None
    assert [row["purpose"] for row in calls] == ["planning"]


def test_default_mode_does_not_call_planner(tmp_path):
    settings = make_settings(tmp_path)
    fake_client = install_model([
        (action("done", summary="Baseline completed"), usage(), "success"),
    ])

    with patch(
        "nova.controller.loop.ModelClient", return_value=fake_client
    ):
        from nova.controller.loop import run_task
        result = run_task("Complete the task", settings)

    assert result["agent_success"] is True
    assert result["planning_mode"] is False
    assert result["plan_revisions"] == 0
    assert fake_client.chat_with_usage.call_count == 1

    episodes, calls = read_database(settings)

    assert episodes[0]["plan"] is None
    assert [row["purpose"] for row in calls] == ["agent_step"]


def test_successful_action_does_not_trigger_replanning(tmp_path):
    settings = make_settings(tmp_path)
    fake_client = install_model([
        (plan(), usage(), "success"),
        (action("read_file", path="existing.py"), usage(), "success"),
        (action("done", summary="Completed"), usage(), "success"),
    ])

    with (
        patch("nova.controller.loop.ModelClient", return_value=fake_client),
        patch(
            "nova.controller.loop._dispatch",
            return_value="existing contents",
        ),
    ):
        from nova.controller.loop import run_task
        result = run_task("Complete the task", settings, planning_mode=True)

    assert result["agent_success"] is True
    assert result["plan_revisions"] == 0

    _, calls = read_database(settings)
    assert [row["purpose"] for row in calls] == [
        "planning",
        "agent_step",
        "agent_step",
    ]
