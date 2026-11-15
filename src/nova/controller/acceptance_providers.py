from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from nova.tools.acceptance_sandbox import (
    AcceptanceSandboxError,
    run_acceptance_call,
)


@dataclass(frozen=True)
class AcceptanceCase:
    name: str
    run: Callable[[dict[str, str]], None]


@dataclass(frozen=True)
class AcceptanceSuite:
    task_id: str
    cases: tuple[AcceptanceCase, ...]


class AcceptanceProviderError(RuntimeError):
    """A trusted provider or its sandbox could not supply valid verification."""


AcceptanceProvider = Callable[[], AcceptanceSuite]

_TASK_ID = "retry_control_flow_002"
_TARGET_PATH = "retrying.py"
_FUNCTION = "call_with_retry"

_SEQUENCE = "$nova_acceptance"
_RECORD = "$nova_acceptance"


def _sequence(name: str, *steps: dict) -> dict:
    return {
        "$nova_acceptance": "sequence_callable",
        "name": name,
        "steps": list(steps),
    }


def _returns(value) -> dict:
    return {"action": "return", "value": value}


def _raises(exception_type: str, message: str) -> dict:
    return {
        "action": "raise",
        "exception_type": exception_type,
        "message": message,
    }


def _recorder(name: str) -> dict:
    return {"$nova_acceptance": "recording_callable", "name": name}


def _exception_types(*names: str) -> dict:
    return {"$nova_acceptance": "exception_types", "items": list(names)}


def _call(sources: dict[str, str], args: list, kwargs: dict) -> dict:
    return run_acceptance_call(
        sources,
        target_path=_TARGET_PATH,
        function=_FUNCTION,
        args=args,
        kwargs=kwargs,
    )


def _acceptance_failure(message: str) -> None:
    raise AssertionError(message)


def _expect_return(observation: dict, expected) -> None:
    if not (
        observation.get('status') == 'returned'
    ):
        raise AssertionError(f'Expected return {expected!r}; observed {observation!r}')
    if not (
        observation.get('result') == expected
    ):
        raise AssertionError(f"Expected return {expected!r}; got {observation.get('result')!r}")


def _expect_raise(observation: dict, expected_type: str) -> dict:
    if not (
        observation.get('status') == 'raised'
    ):
        raise AssertionError(f'Expected {expected_type}; observed {observation!r}')
    exc = observation.get("exception")
    if not (
        isinstance(exc, dict)
    ):
        _acceptance_failure(f'Missing exception observation: {observation!r}')
    if not (
        exc.get('type') == expected_type
    ):
        raise AssertionError(f"Expected {expected_type}; got {exc.get('type')!r}")
    return exc


def _trace(observation: dict, name: str) -> dict:
    callables = observation.get("callables")
    if not (
        isinstance(callables, dict)
    ):
        _acceptance_failure(f'Missing callable trace in {observation!r}')
    trace = callables.get(name)
    if not (
        isinstance(trace, dict)
    ):
        _acceptance_failure(f'Missing trace for callback {name!r}')
    return trace


def _case_first_success(sources: dict[str, str]) -> None:
    operation = _sequence("operation", _returns("ok"))
    sleep = _recorder("sleep")
    observation = _call(
        sources,
        [operation],
        {"max_attempts": 3, "sleep": sleep},
    )
    _expect_return(observation, "ok")
    if not (
        len(_trace(observation, 'operation')['calls']) == 1
    ):
        raise AssertionError('Acceptance check failed at line 116')
    if not (
        _trace(observation, 'sleep')['calls'] == []
    ):
        raise AssertionError('Acceptance check failed at line 117')


def _case_exponential_backoff(sources: dict[str, str]) -> None:
    operation = _sequence(
        "operation",
        _raises("TimeoutError", "temporary"),
        _raises("TimeoutError", "temporary"),
        _returns("recovered"),
    )
    sleep = _recorder("sleep")
    observation = _call(
        sources,
        [operation],
        {
            "max_attempts": 3,
            "base_delay": 0.25,
            "sleep": sleep,
        },
    )
    _expect_return(observation, "recovered")
    if not (
        len(_trace(observation, 'operation')['calls']) == 3
    ):
        raise AssertionError('Acceptance check failed at line 138')
    if not (
        [item['args'] for item in _trace(observation, 'sleep')['calls']] == [[0.25], [0.5]]
    ):
        raise AssertionError('Acceptance check failed at line 139')


def _case_final_exception_identity(sources: dict[str, str]) -> None:
    operation = _sequence(
        "operation",
        _raises("TimeoutError", "first"),
        _raises("TimeoutError", "second"),
        _raises("TimeoutError", "final"),
    )
    sleep = _recorder("sleep")
    observation = _call(
        sources,
        [operation],
        {
            "max_attempts": 3,
            "base_delay": 0.25,
            "sleep": sleep,
        },
    )
    exc = _expect_raise(observation, "TimeoutError")
    errors = _trace(observation, "operation")["errors"]
    if not (
        len(_trace(observation, 'operation')['calls']) == 3
    ):
        raise AssertionError('Acceptance check failed at line 163')
    if not (
        exc.get('token') == errors[-1]['token']
    ):
        raise AssertionError('The final exception object was not propagated unchanged.')
    if not (
        [item['args'] for item in _trace(observation, 'sleep')['calls']] == [[0.25], [0.5]]
    ):
        raise AssertionError('Acceptance check failed at line 167')


def _case_single_attempt(sources: dict[str, str]) -> None:
    operation = _sequence(
        "operation",
        _raises("TimeoutError", "only attempt"),
    )
    sleep = _recorder("sleep")
    observation = _call(
        sources,
        [operation],
        {"max_attempts": 1, "sleep": sleep},
    )
    exc = _expect_raise(observation, "TimeoutError")
    errors = _trace(observation, "operation")["errors"]
    if not (
        exc.get('token') == errors[0]['token']
    ):
        raise AssertionError('Acceptance check failed at line 185')
    if not (
        _trace(observation, 'sleep')['calls'] == []
    ):
        raise AssertionError('Acceptance check failed at line 186')


def _case_non_retryable_exception(sources: dict[str, str]) -> None:
    operation = _sequence(
        "operation",
        _raises("ValueError", "permanent"),
    )
    sleep = _recorder("sleep")
    observation = _call(
        sources,
        [operation],
        {
            "max_attempts": 4,
            "retry_on": _exception_types("TimeoutError"),
            "sleep": sleep,
        },
    )
    exc = _expect_raise(observation, "ValueError")
    if not (
        exc.get('message') == 'permanent'
    ):
        raise AssertionError('Acceptance check failed at line 205')
    if not (
        len(_trace(observation, 'operation')['calls']) == 1
    ):
        raise AssertionError('Acceptance check failed at line 206')
    if not (
        _trace(observation, 'sleep')['calls'] == []
    ):
        raise AssertionError('Acceptance check failed at line 207')


def _case_exception_subclass(sources: dict[str, str]) -> None:
    operation = _sequence(
        "operation",
        _raises("TimeoutError", "subclass of OSError"),
        _returns("ok"),
    )
    observation = _call(
        sources,
        [operation],
        {
            "max_attempts": 2,
            "retry_on": _exception_types("OSError"),
            "sleep": _recorder("sleep"),
        },
    )
    _expect_return(observation, "ok")
    if not (
        len(_trace(observation, 'operation')['calls']) == 2
    ):
        raise AssertionError('Acceptance check failed at line 226')


def _case_zero_attempts(sources: dict[str, str]) -> None:
    operation = _sequence("operation", _returns("unused"))
    observation = _call(
        sources,
        [operation],
        {
            "max_attempts": 0,
            "sleep": _recorder("sleep"),
        },
    )
    _expect_raise(observation, "ValueError")
    if not (
        _trace(observation, 'operation')['calls'] == []
    ):
        raise AssertionError('Acceptance check failed at line 240')


def _case_negative_base_delay(sources: dict[str, str]) -> None:
    operation = _sequence("operation", _returns("unused"))
    observation = _call(
        sources,
        [operation],
        {
            "max_attempts": 1,
            "base_delay": -0.1,
            "sleep": _recorder("sleep"),
        },
    )
    _expect_raise(observation, "ValueError")
    if not (
        _trace(observation, 'operation')['calls'] == []
    ):
        raise AssertionError('Acceptance check failed at line 255')


def _case_boolean_attempts_rejected(sources: dict[str, str]) -> None:
    operation = _sequence("operation", _returns("unused"))
    observation = _call(
        sources,
        [operation],
        {
            "max_attempts": True,
            "sleep": _recorder("sleep"),
        },
    )
    _expect_raise(observation, "TypeError")
    if not (
        _trace(observation, 'operation')['calls'] == []
    ):
        raise AssertionError('Acceptance check failed at line 269')


def _case_non_integer_attempts(
    sources: dict[str, str],
    invalid_value: object,
) -> None:
    operation = _sequence("operation", _returns("unused"))
    observation = _call(
        sources,
        [operation],
        {
            "max_attempts": invalid_value,
            "sleep": _recorder("sleep"),
        },
    )
    _expect_raise(observation, "TypeError")
    if _trace(observation, "operation")["calls"]:
        raise AssertionError("Operation was called for invalid max_attempts.")


def _case_string_attempts(sources: dict[str, str]) -> None:
    _case_non_integer_attempts(sources, "3")


def _case_float_attempts(sources: dict[str, str]) -> None:
    _case_non_integer_attempts(sources, 1.5)


_CFD002_CASES = (
    AcceptanceCase("success_on_first_attempt_does_not_sleep", _case_first_success),
    AcceptanceCase("transient_failures_use_exponential_backoff", _case_exponential_backoff),
    AcceptanceCase("exhaustion_raises_final_exception_without_final_sleep", _case_final_exception_identity),
    AcceptanceCase("single_attempt_propagates_without_sleeping", _case_single_attempt),
    AcceptanceCase("non_retryable_exception_propagates_immediately", _case_non_retryable_exception),
    AcceptanceCase("retry_exception_subclasses_are_supported", _case_exception_subclass),
    AcceptanceCase("zero_attempts_are_rejected_before_calling_operation", _case_zero_attempts),
    AcceptanceCase("negative_base_delay_is_rejected", _case_negative_base_delay),
    AcceptanceCase("boolean_attempt_count_is_rejected", _case_boolean_attempts_rejected),
    AcceptanceCase("string_attempt_count_is_rejected", _case_string_attempts),
    AcceptanceCase("float_attempt_count_is_rejected", _case_float_attempts),
)

ACCEPTANCE_EXPECTED_CASE_NAMES: dict[str, tuple[str, ...]] = {
    _TASK_ID: (
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
    ),
}


def retry_control_flow_002_provider() -> AcceptanceSuite:
    return AcceptanceSuite(task_id=_TASK_ID, cases=_CFD002_CASES)


ACCEPTANCE_PROVIDERS: dict[str, AcceptanceProvider] = {
    _TASK_ID: retry_control_flow_002_provider,
}


def execute_acceptance_suite(
    task_id: str,
    sources: dict[str, str],
) -> dict:
    """Run a trusted registered suite and validate its entire case inventory."""
    provider = ACCEPTANCE_PROVIDERS.get(task_id)
    if provider is None:
        raise AcceptanceProviderError(
            f"No trusted acceptance provider is registered for task id {task_id!r}."
        )

    expected_names = ACCEPTANCE_EXPECTED_CASE_NAMES.get(task_id)
    if not expected_names:
        raise AcceptanceProviderError(
            f"No trusted expected-case inventory is registered for {task_id!r}."
        )

    try:
        suite = provider()
    except Exception as exc:
        raise AcceptanceProviderError(
            f"Acceptance provider failed: {type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(suite, AcceptanceSuite):
        raise AcceptanceProviderError("Acceptance provider returned an invalid suite.")
    if suite.task_id != task_id:
        raise AcceptanceProviderError(
            f"Provider task id mismatch: expected {task_id!r}, got {suite.task_id!r}."
        )

    actual_names = tuple(case.name for case in suite.cases)
    if actual_names != expected_names:
        raise AcceptanceProviderError(
            "Acceptance suite case inventory mismatch: "
            f"expected {expected_names!r}, got {actual_names!r}."
        )

    if not suite.cases or any(
        not isinstance(case, AcceptanceCase)
        or not isinstance(case.name, str)
        or not case.name
        or not callable(case.run)
        for case in suite.cases
    ):
        raise AcceptanceProviderError("Acceptance suite contains an invalid case.")

    results = []
    for case in suite.cases:
        try:
            case.run(sources)
        except AssertionError as exc:
            results.append({
                "name": case.name,
                "status": "failed",
                "reason": str(exc)[:2000],
            })
        except AcceptanceSandboxError as exc:
            raise AcceptanceProviderError(
                f"Sandbox unavailable during {case.name}: {exc}"
            ) from exc
        except Exception as exc:
            raise AcceptanceProviderError(
                f"Trusted case runner failed during {case.name}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        else:
            results.append({"name": case.name, "status": "passed"})

    passed = sum(item["status"] == "passed" for item in results)
    failed = len(results) - passed
    return {
        "task_id": task_id,
        "status": "passed" if failed == 0 else "failed",
        "case_count": len(results),
        "cases_passed": passed,
        "cases_failed": failed,
        "cases": results,
    }
