import pytest

from nova.tools.behavioral_probe import (
    BehavioralProbeError,
    run_behavioral_probe,
    validate_behavioral_probe,
)

FILES = {
    "tokenizer.py": "def split_fields(source):\n    return source.split(';')\n"
}

PROBE = {
    "kind": "function_call",
    "path": "tokenizer.py",
    "function": "split_fields",
    "args": ["a=1;b=2"],
    "kwargs": {},
    "expected_result": ["a=1", "b=2"],
}


def test_valid_probe_is_normalized():
    result = validate_behavioral_probe(FILES, PROBE)
    assert result["path"] == "tokenizer.py"
    assert result["observed_python_files"] == FILES


def test_unobserved_source_is_rejected():
    with pytest.raises(BehavioralProbeError, match="observed"):
        validate_behavioral_probe(FILES, {**PROBE, "path": "secret.py"})


def test_path_traversal_is_rejected():
    with pytest.raises(BehavioralProbeError, match="not permitted"):
        validate_behavioral_probe(FILES, {**PROBE, "path": "../secret.py"})


def test_private_function_is_rejected():
    with pytest.raises(BehavioralProbeError, match="public"):
        validate_behavioral_probe(FILES, {**PROBE, "function": "__import__"})


def test_non_finite_number_is_rejected():
    with pytest.raises(BehavioralProbeError, match="finite"):
        validate_behavioral_probe(FILES, {**PROBE, "expected_result": float("nan")})


def test_unexpected_probe_fields_are_rejected():
    with pytest.raises(BehavioralProbeError, match="fields"):
        validate_behavioral_probe(FILES, {**PROBE, "code": "print('unsafe')"})


def test_missing_function_is_rejected():
    with pytest.raises(BehavioralProbeError, match="not found"):
        validate_behavioral_probe(FILES, {**PROBE, "function": "missing"})

def _run_probe_with_execution(tmp_path, monkeypatch, probe, execution):
    import json
    from types import SimpleNamespace

    function_output = (
        "NOVA_BHT_FUNCTION_RESULT:" + json.dumps(execution) + "\n"
    )
    bridge = {
        "sandbox_succeeded": True,
        "exit_code": 0,
        "stdout": function_output,
        "stderr": "",
        "duration_seconds": 0.1,
    }
    outputs = iter((
        SimpleNamespace(returncode=0, stdout="/workspace-source\n", stderr=""),
        SimpleNamespace(
            returncode=0,
            stdout="NOVA_BHT_RESULT:" + json.dumps(bridge) + "\n",
            stderr="",
        ),
    ))
    monkeypatch.setattr(
        "nova.tools.behavioral_probe.subprocess.run",
        lambda *args, **kwargs: next(outputs),
    )
    return run_behavioral_probe(FILES, probe, source_root=tmp_path)


def test_expected_exception_is_prediction_match(tmp_path, monkeypatch):
    expected = {
        "type": "ValueError",
        "message": "Unterminated quoted value",
    }
    result = _run_probe_with_execution(
        tmp_path,
        monkeypatch,
        {
            **PROBE,
            "expected_result": None,
            "expected_exception": expected,
        },
        {"harness_ok": True, "raised": expected},
    )

    assert result["verdict"] == "PREDICTION_MATCHED"
    assert result["prediction_matched"] is True
    assert result["probe_completed"] is True
    assert result["actual_exception"] == expected


def test_expected_exception_message_must_match_exactly(tmp_path, monkeypatch):
    expected = {
        "type": "ValueError",
        "message": "Unterminated quoted value",
    }
    actual = {
        "type": "ValueError",
        "message": "Different error",
    }
    result = _run_probe_with_execution(
        tmp_path,
        monkeypatch,
        {
            **PROBE,
            "expected_result": None,
            "expected_exception": expected,
        },
        {"harness_ok": True, "raised": actual},
    )

    assert result["verdict"] == "PREDICTION_MISMATCHED"
    assert result["prediction_matched"] is False


def test_expected_exception_type_must_match_exactly(tmp_path, monkeypatch):
    expected = {
        "type": "ValueError",
        "message": "Unterminated quoted value",
    }
    actual = {
        "type": "TypeError",
        "message": "Unterminated quoted value",
    }
    result = _run_probe_with_execution(
        tmp_path,
        monkeypatch,
        {
            **PROBE,
            "expected_result": None,
            "expected_exception": expected,
        },
        {"harness_ok": True, "raised": actual},
    )

    assert result["verdict"] == "PREDICTION_MISMATCHED"


def test_return_value_mismatches_expected_exception(tmp_path, monkeypatch):
    expected = {
        "type": "ValueError",
        "message": "Unterminated quoted value",
    }
    result = _run_probe_with_execution(
        tmp_path,
        monkeypatch,
        {
            **PROBE,
            "expected_result": None,
            "expected_exception": expected,
        },
        {"harness_ok": True, "actual": ["a=1", "b=2"]},
    )

    assert result["verdict"] == "PREDICTION_MISMATCHED"
    assert result["prediction_matched"] is False


def test_legacy_probe_without_exception_field_remains_valid():
    result = validate_behavioral_probe(FILES, PROBE)
    assert result["expected_exception"] is None


def test_invalid_expected_exception_is_rejected():
    invalid = {
        **PROBE,
        "expected_exception": {
            "type": "__import__",
            "message": "error",
        },
    }
    with pytest.raises(BehavioralProbeError, match="expected exception"):
        validate_behavioral_probe(FILES, invalid)


def test_exception_and_return_expectations_cannot_conflict():
    invalid = {
        **PROBE,
        "expected_exception": {
            "type": "ValueError",
            "message": "error",
        },
    }
    with pytest.raises(BehavioralProbeError, match="expected_result"):
        validate_behavioral_probe(FILES, invalid)


def test_typed_record_is_serialized_without_model_authored_escaping():
    typed = {
        "fields": [
            {"key": "name", "type": "quoted", "value": 'A "quoted; value"'},
            {"key": "status", "type": "unquoted", "value": "ok"},
        ]
    }
    result = validate_behavioral_probe(
            FILES, {**PROBE, "args": [typed]}, allow_typed_record=True
        )
    assert result["args"] == [r'name="A \"quoted; value\"";status=ok']


def test_typed_record_rejects_delimiter_in_unquoted_value():
    typed = {
        "fields": [
            {"key": "status", "type": "unquoted", "value": "not;safe"},
        ]
    }
    with pytest.raises(BehavioralProbeError, match="Unquoted typed values"):
        validate_behavioral_probe(
            FILES, {**PROBE, "args": [typed]}, allow_typed_record=True
        )


def test_typed_record_rejects_unknown_field_shape():
    typed = {
        "fields": [
            {"key": "x", "type": "quoted", "value": "y", "extra": 1}
        ]
    }
    with pytest.raises(BehavioralProbeError, match="key, type, and value"):
        validate_behavioral_probe(
            FILES, {**PROBE, "args": [typed]}, allow_typed_record=True
        )


def test_typed_record_shape_is_preserved_without_explicit_opt_in():
    typed = {
        "fields": [
            {"key": "name", "type": "quoted", "value": "ordinary dictionary"},
        ]
    }
    result = validate_behavioral_probe(FILES, {**PROBE, "args": [typed]})
    assert result["args"] == [typed]


def test_cfd001_postwrite_probes_match_validator():
    """Regression: probes from _cfd001_postwrite_acceptance_probes() must
    pass the real validator. Historically they carried extra fields
    (symbol, expected_present) that validate_behavioral_probe rejects.

    If this fails, the live post-write gate will fail before running any
    probe. The autouse stub in test_causal_review_controller.py does not
    catch this because it bypasses validation.
    """
    from nova.controller.loop import (
        _CFD001_ACCEPTANCE_CASES,
        _cfd001_postwrite_acceptance_probes,
    )
    from nova.tools.behavioral_probe import validate_behavioral_probe

    observed = {
        "parser.py": "def parse_record(source):\n    return {}\n",
        "tokenizer.py": "def split_fields(source):\n    return []\n",
    }

    probes = _cfd001_postwrite_acceptance_probes()
    assert len(probes) == len(_CFD001_ACCEPTANCE_CASES) == 11

    required = {
        "kind", "path", "function", "args", "kwargs",
        "expected_result", "expected_exception",
    }
    legacy = required - {"expected_exception"}

    for i, probe in enumerate(probes):
        assert set(probe) in (legacy, required), (
            f"Probe {i} has unexpected field set: {sorted(probe)}. "
            f"Validator accepts {sorted(legacy)} or {sorted(required)}."
        )
        normalized = validate_behavioral_probe(observed, probe)
        assert normalized["kind"] == "function_call"


def test_run_behavioral_probe_rejects_drifted_probe_before_sandbox():
    """Meta-test: run_behavioral_probe validates the probe schema before any
    sandbox call. A probe with the historical extra fields must raise
    BehavioralProbeError, not silently reach Docker."""
    import pytest

    from nova.controller.loop import _cfd001_postwrite_acceptance_probes
    from nova.tools.behavioral_probe import (
        BehavioralProbeError,
        run_behavioral_probe,
    )

    observed = {
        "parser.py": "def parse_record(source):\n    return {}\n",
        "tokenizer.py": "def split_fields(source):\n    return []\n",
    }

    probe = _cfd001_postwrite_acceptance_probes()[0]

    drifted = dict(probe)
    drifted["symbol"] = ""
    drifted["expected_present"] = False
    with pytest.raises(BehavioralProbeError, match="Invalid behavioral probe fields"):
        run_behavioral_probe(observed, drifted)

    drifted2 = dict(probe)
    drifted2["symbol"] = ""
    with pytest.raises(BehavioralProbeError, match="Invalid behavioral probe fields"):
        run_behavioral_probe(observed, drifted2)
