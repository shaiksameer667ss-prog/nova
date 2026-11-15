from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from nova.controller import acceptance_providers as providers
from nova.tools import acceptance_sandbox


def _trace(count=0, *, delays=(), errors=()):
    return {
        "calls": [
            {"args": list(args), "kwargs": {}}
            for args in delays
        ] if delays else [
            {"args": [], "kwargs": {}}
            for _ in range(count)
        ],
        "errors": list(errors),
    }


def _successful_observation(name, kwargs):
    operation = {
        "calls": [],
        "errors": [],
    }
    sleep = {"calls": [], "errors": []}
    observation = {"callables": {"operation": operation, "sleep": sleep}}

    maximum = kwargs["max_attempts"]
    delay = kwargs.get("base_delay")

    if isinstance(maximum, bool) or not isinstance(maximum, int):
        observation.update({
            "status": "raised",
            "exception": {"type": "TypeError", "message": "invalid attempts"},
        })
        return observation

    if maximum == 0:
        observation.update({
            "status": "raised",
            "exception": {"type": "ValueError", "message": "invalid attempts"},
        })
        return observation

    if delay is not None and delay < 0:
        observation.update({
            "status": "raised",
            "exception": {"type": "ValueError", "message": "negative delay"},
        })
        return observation

    if "retry_on" in kwargs:
        names = kwargs["retry_on"]["items"]
        if names == ["OSError"]:
            operation["calls"] = [{}, {}]
            observation.update({"status": "returned", "result": "ok"})
        else:
            operation["calls"] = [{}]
            observation.update({
                "status": "raised",
                "exception": {
                    "type": "ValueError",
                    "message": "permanent",
                },
            })
        return observation

    if maximum == 1:
        token = "operation:0"
        operation["calls"] = [{}]
        operation["errors"] = [{
            "token": token,
            "type": "TimeoutError",
            "message": "only attempt",
        }]
        observation.update({
            "status": "raised",
            "exception": {
                "type": "TimeoutError",
                "message": "only attempt",
                "token": token,
            },
        })
        return observation

    if delay == 0.25:
        # Distinguish the two 0.25 cases by the callback descriptor
        # supplied in args[0], which the mock receives through the wrapper.
        # The provider's sequence has two failures followed by recovery,
        # or three failures ending in the final exception.
        if _CURRENT_OPERATION_LAST_ACTION == "return":
            operation["calls"] = [{}, {}, {}]
            operation["errors"] = [
                {"token": "operation:0"},
                {"token": "operation:1"},
            ]
            sleep["calls"] = [
                {"args": [0.25], "kwargs": {}},
                {"args": [0.5], "kwargs": {}},
            ]
            observation.update({"status": "returned", "result": "recovered"})
        else:
            operation["calls"] = [{}, {}, {}]
            operation["errors"] = [
                {"token": "operation:0"},
                {"token": "operation:1"},
                {"token": "operation:2"},
            ]
            sleep["calls"] = [
                {"args": [0.25], "kwargs": {}},
                {"args": [0.5], "kwargs": {}},
            ]
            observation.update({
                "status": "raised",
                "exception": {
                    "type": "TimeoutError",
                    "message": "final",
                    "token": "operation:2",
                },
            })
        return observation

    operation["calls"] = [{}]
    observation.update({"status": "returned", "result": "ok"})
    return observation


_CURRENT_OPERATION_LAST_ACTION = None


def _mock_run_acceptance_call(monkeypatch, *, first_success_mismatch=False):
    def fake_run(
        sources,
        *,
        target_path,
        function,
        args,
        kwargs,
        **unused,
    ):
        global _CURRENT_OPERATION_LAST_ACTION
        _CURRENT_OPERATION_LAST_ACTION = args[0]["steps"][-1]["action"]

        observation = _successful_observation(
            function,
            kwargs,
        )
        if (
            first_success_mismatch
            and kwargs.get("max_attempts") == 3
            and "base_delay" not in kwargs
        ):
            observation["result"] = "wrong"
        return observation

    monkeypatch.setattr(providers, "run_acceptance_call", fake_run)


def test_trusted_checks_remain_active_under_python_optimization():
    project_root = Path(providers.__file__).resolve().parents[3]
    script = (
        "from nova.controller.acceptance_providers import _expect_return\n"
        "_expect_return({'status': 'returned', 'result': 'wrong'}, 'right')\n"
    )

    result = subprocess.run(
        [sys.executable, "-O", "-c", script],
        cwd=project_root / "src",
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "AssertionError" in result.stderr


def test_cfd002_registry_and_exact_case_inventory():
    suite = providers.retry_control_flow_002_provider()

    assert providers.ACCEPTANCE_PROVIDERS[_TASK_ID]() == suite
    assert suite.task_id == _TASK_ID
    assert tuple(case.name for case in suite.cases) == (
        "success_on_first_attempt_does_not_sleep",
        "transient_failures_use_exponential_backoff",
        "exhaustion_raises_final_exception_without_final_sleep",
        "single_attempt_propagates_without_sleeping",
        "non_retryable_exception_propagates_immediately",
        "retry_exception_subclasses_are_supported",
        "zero_attempts_are_rejected_before_calling_operation",
        "negative_base_delay_is_rejected",
        "boolean_attempt_count_is_rejected",
        "string_attempt_count_is_rejected",
        "float_attempt_count_is_rejected",
    )


_TASK_ID = "retry_control_flow_002"


def test_all_trusted_acceptance_cases_pass_with_valid_observations(monkeypatch):
    _mock_run_acceptance_call(monkeypatch)

    result = providers.execute_acceptance_suite(
        _TASK_ID,
        {"retrying.py": "def call_with_retry(*args, **kwargs): return None\n"},
    )

    assert result["status"] == "passed"
    assert result["case_count"] == 11
    assert result["cases_passed"] == 11
    assert result["cases_failed"] == 0
    assert all(item["status"] == "passed" for item in result["cases"])


def test_acceptance_assertion_failure_is_not_reported_as_success(monkeypatch):
    _mock_run_acceptance_call(monkeypatch, first_success_mismatch=True)

    result = providers.execute_acceptance_suite(
        _TASK_ID,
        {"retrying.py": "def call_with_retry(*args, **kwargs): return None\n"},
    )

    assert result["status"] == "failed"
    assert result["cases_failed"] == 1
    assert result["cases"][0]["status"] == "failed"


def test_unknown_task_id_fails_closed():
    with pytest.raises(
        providers.AcceptanceProviderError,
        match="No trusted acceptance provider",
    ):
        providers.execute_acceptance_suite(
            "unknown_task",
            {"retrying.py": "VALUE = 1\n"},
        )


def test_incomplete_suite_inventory_fails_closed(monkeypatch):
    original = providers.ACCEPTANCE_PROVIDERS[_TASK_ID]

    monkeypatch.setitem(
        providers.ACCEPTANCE_PROVIDERS,
        _TASK_ID,
        lambda: providers.AcceptanceSuite(
            task_id=_TASK_ID,
            cases=(providers.AcceptanceCase("only_one_case", lambda _: None),),
        ),
    )

    with pytest.raises(
        providers.AcceptanceProviderError,
        match="case inventory mismatch",
    ):
        providers.execute_acceptance_suite(
            _TASK_ID,
            {"retrying.py": "VALUE = 1\n"},
        )

    assert providers.ACCEPTANCE_PROVIDERS[_TASK_ID] is not original


def test_provider_task_id_mismatch_fails_closed(monkeypatch):
    monkeypatch.setitem(
        providers.ACCEPTANCE_PROVIDERS,
        _TASK_ID,
        lambda: providers.AcceptanceSuite(
            task_id="different_task",
            cases=providers._CFD002_CASES,
        ),
    )

    with pytest.raises(
        providers.AcceptanceProviderError,
        match="task id mismatch",
    ):
        providers.execute_acceptance_suite(
            _TASK_ID,
            {"retrying.py": "VALUE = 1\n"},
        )


def test_unsafe_candidate_paths_are_rejected():
    with pytest.raises(
        acceptance_sandbox.AcceptanceSandboxError,
        match="Unsafe",
    ):
        acceptance_sandbox._normalize_sources({
            "../outside.py": "VALUE = 1\n",
        })


def test_non_python_candidate_paths_are_rejected():
    with pytest.raises(
        acceptance_sandbox.AcceptanceSandboxError,
        match="Unsafe",
    ):
        acceptance_sandbox._normalize_sources({
            "retrying.txt": "not python",
        })


def test_unknown_acceptance_descriptors_are_rejected():
    with pytest.raises(
        acceptance_sandbox.AcceptanceSandboxError,
        match="Unknown acceptance descriptor",
    ):
        acceptance_sandbox._validate_case_value({
            "$nova_acceptance": "arbitrary_code",
            "code": "pass",
        })
