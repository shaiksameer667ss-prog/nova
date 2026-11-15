"""Focused tests for the internal generate_candidate branch in loop.py."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nova.config import Settings
from nova.controller.loop import (
    _ensure_local_ollama_model_unloaded,
    run_task,
)


def action(kind, **kwargs):
    return json.dumps({"action": kind, **kwargs})


def usage():
    return {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "usage_complete": True,
        "usage_json": "{}",
    }


def install_responses(responses):
    client = MagicMock()
    remaining = iter(responses)

    def respond(*args, **kwargs):
        return next(remaining), usage(), "success"

    client.chat_with_usage.side_effect = respond
    client.close = MagicMock()
    return client


def make_settings(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "tokenizer.py").write_text(
        "def split_fields(source):\n    return source.split(';')\n",
        encoding="utf-8",
    )
    return Settings(
        base_url="http://localhost:11434/v1",
        api_key="test",
        model="test-model",
        workspace=workspace,
        db=tmp_path / "test.db",
        max_steps=10,
        temperature=0.2,
    )


FAKE_CONTENT = "def split_fields(source):\n    return ['ok']\n"


def fake_candidate():
    return {
        "path": "tokenizer.py",
        "content": FAKE_CONTENT,
        "model_id": "fake-base",
        "adapter_id": "fake-v6",
        "adapter_sha256": "0" * 64,
        "prompt_sha256": "0" * 64,
        "generation_config": {},
        "candidate_source": "internal",
    }


def run_with(responses, gen_fn, tmp_path, events=None):
    settings = make_settings(tmp_path)
    client = install_responses(responses)
    calls = []
    dispatches = []

    def gen(**kwargs):
        calls.append(kwargs)
        if events is not None:
            events.append("generation")
        return gen_fn(**kwargs)

    def handoff(active_settings):
        if events is not None:
            events.append("gpu_handoff")
        return {"status": "test_handoff"}

    def dispatch(a, active_settings):
        dispatches.append(a)
        if a["action"] == "write_file":
            (active_settings.workspace / a["path"]).write_text(
                a["content"], encoding="utf-8"
            )
        return "ok"

    with (
        patch("nova.controller.loop.ModelClient", return_value=client),
        patch("nova.controller.loop.generate_candidate", side_effect=gen),
        patch(
            "nova.controller.loop._ensure_local_ollama_model_unloaded",
            side_effect=handoff,
        ),
        patch("nova.controller.loop._dispatch", side_effect=dispatch),
    ):
        result = run_task("Repair tokenizer.", settings)

    return result, calls, dispatches


def test_generate_candidate_happy_path(tmp_path):
    def gen(**kwargs):
        return fake_candidate()

    _result, calls, dispatches = run_with(
        [
            action("generate_candidate", path="tokenizer.py", task_context="t"),
            action("done", summary="Loaded."),
            action("done", summary="Finished."),
        ],
        gen,
        tmp_path,
    )
    assert len(calls) == 1
    assert calls[0]["path"] == "tokenizer.py"
    writes = [d for d in dispatches if d["action"] == "write_file"]
    assert len(writes) == 1
    assert writes[0]["path"] == "tokenizer.py"
    assert writes[0]["content"] == FAKE_CONTENT


def test_manual_generate_candidate_handoff_precedes_bridge(tmp_path):
    events = []

    run_with(
        [
            action("generate_candidate", path="tokenizer.py", task_context="manual"),
            action("done", summary="Apply candidate."),
            action("done", summary="Finished."),
        ],
        lambda **kwargs: fake_candidate(),
        tmp_path,
        events=events,
    )

    assert events == ["gpu_handoff", "generation"]


def test_generate_candidate_failure_does_not_write(tmp_path):
    def gen(**kwargs):
        return {"error": "bridge not configured"}

    _result, calls, dispatches = run_with(
        [
            action("generate_candidate", path="tokenizer.py", task_context="t"),
            action("generate_candidate", path="tokenizer.py", task_context="t"),
            action("done", summary="Giving up."),
        ],
        gen,
        tmp_path,
    )
    assert len(calls) == 2
    writes = [d for d in dispatches if d["action"] == "write_file"]
    assert len(writes) == 0


def test_generate_candidate_refused_when_candidate_available(tmp_path):
    def gen(**kwargs):
        return fake_candidate()

    _result, calls, dispatches = run_with(
        [
            action("generate_candidate", path="tokenizer.py", task_context="t"),
            action("generate_candidate", path="tokenizer.py", task_context="t"),
            action("generate_candidate", path="tokenizer.py", task_context="t"),
            action("done", summary="Finished."),
            action("done", summary="Finished."),
        ],
        gen,
        tmp_path,
    )
    assert len(calls) == 1
    writes = [d for d in dispatches if d["action"] == "write_file"]
    assert len(writes) == 1
    assert writes[0]["content"] == FAKE_CONTENT


def test_generate_candidate_refused_after_dispatch(tmp_path):
    def gen(**kwargs):
        return fake_candidate()

    _result, calls, dispatches = run_with(
        [
            action("generate_candidate", path="tokenizer.py", task_context="t"),
            action("done", summary="Loaded."),
            action("generate_candidate", path="tokenizer.py", task_context="t"),
            action("done", summary="Finished."),
        ],
        gen,
        tmp_path,
    )
    assert len(calls) == 1
    writes = [d for d in dispatches if d["action"] == "write_file"]
    assert len(writes) == 1

# ------------------------------------------------------------
# Preflight integration tests.
# ------------------------------------------------------------
def run_preflight_case(
    responses,
    gen_fn,
    tmp_path,
    *,
    benchmark_task_id="cross_file_dependency_001",
    pre_selected_candidate=None,
    handoff_fn=None,
    events=None,
):
    settings = make_settings(tmp_path)
    client = install_responses(responses)
    calls = []
    dispatches = []

    original_chat = client.chat_with_usage.side_effect

    def tracked_chat(*args, **kwargs):
        if events is not None:
            events.append("controller_inference")
        return original_chat(*args, **kwargs)

    client.chat_with_usage.side_effect = tracked_chat

    def gen(**kwargs):
        calls.append(kwargs)
        if events is not None:
            events.append("generation")
        return gen_fn(**kwargs)

    def handoff(active_settings):
        if events is not None:
            events.append("gpu_handoff")
        if handoff_fn is not None:
            return handoff_fn(active_settings)
        return {"status": "test_handoff"}

    def dispatch(a, active_settings):
        dispatches.append(a)
        if a["action"] == "write_file":
            (active_settings.workspace / a["path"]).write_text(
                a["content"], encoding="utf-8"
            )
        return "ok"

    with (
        patch("nova.controller.loop.ModelClient", return_value=client),
        patch("nova.controller.loop.generate_candidate", side_effect=gen),
        patch(
            "nova.controller.loop._ensure_local_ollama_model_unloaded",
            side_effect=handoff,
        ),
        patch("nova.controller.loop._dispatch", side_effect=dispatch),
    ):
        result = run_task(
            "Repair tokenizer.",
            settings,
            benchmark_task_id=benchmark_task_id,
            pre_selected_candidate=pre_selected_candidate,
        )

    return result, calls, dispatches, client, settings


def test_preflight_skips_when_candidate_supplied(tmp_path):
    result, calls, dispatches, _, _ = run_preflight_case(
        [
            action("done", summary="Use supplied candidate."),
            action("done", summary="Finished."),
        ],
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("generator must not run")
        ),
        tmp_path,
        pre_selected_candidate=fake_candidate(),
    )

    assert calls == []
    assert result["candidate_preflight"]["status"] == "skipped"
    assert (
        result["candidate_preflight"]["reason"]
        == "candidate_supplied_by_caller"
    )

    writes = [item for item in dispatches if item["action"] == "write_file"]
    assert len(writes) == 1
    assert writes[0]["content"] == FAKE_CONTENT


def test_preflight_skips_for_non_cfd001_without_transcript_event(tmp_path):
    result, calls, _, _, _ = run_preflight_case(
        [
            action("done", summary="No internal candidate required."),
            action("done", summary="Finished."),
        ],
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("generator must not run")
        ),
        tmp_path,
        benchmark_task_id="task_001",
    )

    assert calls == []
    assert result["candidate_preflight"] is None


def test_preflight_failure_falls_back_without_retry(tmp_path):
    result, calls, dispatches, _, _ = run_preflight_case(
        [
            action("generate_candidate", path="tokenizer.py", task_context="retry"),
            action(
                "write_file",
                path="tokenizer.py",
                content=FAKE_CONTENT,
            ),
            action("done", summary="Finished ordinary repair."),
        ],
        lambda **kwargs: {"error": "simulated bridge failure"},
        tmp_path,
    )

    assert len(calls) == 1
    assert result["candidate_preflight"]["attempted"] is True
    assert result["candidate_preflight"]["status"] == "failed"
    assert "simulated bridge failure" in result["candidate_preflight"]["error"]

    writes = [item for item in dispatches if item["action"] == "write_file"]
    assert len(writes) == 1
    assert writes[0]["content"] == FAKE_CONTENT
    assert "stop_reason" in result


def test_preflight_success_supplies_candidate_and_records_provenance(tmp_path):
    result, calls, dispatches, _, _ = run_preflight_case(
        [
            action("done", summary="Apply the prepared candidate."),
            action("done", summary="Finished."),
        ],
        lambda **kwargs: fake_candidate(),
        tmp_path,
    )

    assert len(calls) == 1
    assert result["candidate_preflight"]["status"] == "succeeded"
    assert result["candidate_preflight"]["provenance"]["model_id"] == "fake-base"

    writes = [item for item in dispatches if item["action"] == "write_file"]
    assert len(writes) == 1
    assert writes[0]["path"] == "tokenizer.py"
    assert writes[0]["content"] == FAKE_CONTENT


def test_preflight_precedes_first_controller_inference(tmp_path):
    events = []

    run_preflight_case(
        [
            action("done", summary="Apply the candidate."),
            action("done", summary="Finished."),
        ],
        lambda **kwargs: fake_candidate(),
        tmp_path,
        events=events,
    )

    assert events.index("gpu_handoff") < events.index("generation")
    assert events.index("generation") < events.index("controller_inference")


def test_preflight_handoff_failure_prevents_bridge_and_falls_back(tmp_path):
    def fail_handoff(settings):
        raise RuntimeError("controller model could not be unloaded")

    result, calls, dispatches, _, _ = run_preflight_case(
        [
            action(
                "write_file",
                path="tokenizer.py",
                content=FAKE_CONTENT,
            ),
            action("done", summary="Finished ordinary repair."),
        ],
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("bridge must not run after failed GPU handoff")
        ),
        tmp_path,
        handoff_fn=fail_handoff,
    )

    assert calls == []
    assert result["candidate_preflight"]["status"] == "failed"
    assert "could not be unloaded" in result["candidate_preflight"]["error"]

    writes = [item for item in dispatches if item["action"] == "write_file"]
    assert len(writes) == 1


def test_generate_candidate_action_refused_after_preflight_success(tmp_path):
    result, calls, dispatches, _, _ = run_preflight_case(
        [
            action("generate_candidate", path="tokenizer.py", task_context="duplicate"),
            action("done", summary="Apply prepared candidate."),
            action("done", summary="Finished."),
        ],
        lambda **kwargs: fake_candidate(),
        tmp_path,
    )

    assert len(calls) == 1
    assert result["candidate_preflight"]["status"] == "succeeded"

    writes = [item for item in dispatches if item["action"] == "write_file"]
    assert len(writes) == 1
    assert writes[0]["content"] == FAKE_CONTENT


def test_ollama_handoff_stops_resident_controller_model(tmp_path):

    settings = make_settings(tmp_path)
    ps_loaded = SimpleNamespace(
        returncode=0,
        stdout="NAME ID SIZE PROCESSOR UNTIL\ntest-model abc 5GB 100% GPU 4m\n",
        stderr="",
    )
    stop_ok = SimpleNamespace(returncode=0, stdout="stopped", stderr="")
    ps_empty = SimpleNamespace(
        returncode=0,
        stdout="NAME ID SIZE PROCESSOR UNTIL\n",
        stderr="",
    )
    responses = iter([ps_loaded, stop_ok, ps_empty])
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return next(responses)

    with patch("nova.controller.loop.subprocess.run", side_effect=fake_run):
        result = _ensure_local_ollama_model_unloaded(settings)

    assert commands == [
        ["ollama", "ps"],
        ["ollama", "stop", "test-model"],
        ["ollama", "ps"],
    ]
    assert result["status"] == "unloaded"


def test_ollama_handoff_fails_if_model_remains_resident(tmp_path):

    settings = make_settings(tmp_path)
    ps_loaded = SimpleNamespace(
        returncode=0,
        stdout="NAME ID SIZE PROCESSOR UNTIL\ntest-model abc 5GB 100% GPU 4m\n",
        stderr="",
    )
    stop_ok = SimpleNamespace(returncode=0, stdout="stopped", stderr="")
    responses = iter([ps_loaded, stop_ok, ps_loaded])

    with patch(
        "nova.controller.loop.subprocess.run",
        side_effect=lambda *args, **kwargs: next(responses),
    ):
        try:
            _ensure_local_ollama_model_unloaded(settings)
        except RuntimeError as exc:
            assert "remains resident" in str(exc)
        else:
            raise AssertionError("handoff must fail when model remains resident")
def test_generate_candidate_budget_exhausted_after_failures(tmp_path):
    def gen(**kwargs):
        return {"error": "simulated bridge failure"}

    _result, calls, dispatches = run_with(
        [
            action("generate_candidate", path="tokenizer.py", task_context="t"),
            action("generate_candidate", path="tokenizer.py", task_context="t"),
            action("generate_candidate", path="tokenizer.py", task_context="t"),
            action("done", summary="Continue."),
            action("done", summary="Finished."),
        ],
        gen,
        tmp_path,
    )

    # Two failed attempts are allowed; the third request is budget-exhausted.
    assert len(calls) == 2
    writes = [d for d in dispatches if d["action"] == "write_file"]
    assert writes == []
