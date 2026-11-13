import pytest

from nova.controller.hypothesis_testing import (
    HypothesisProbeError,
    evaluate_static_probe,
)

FILES = {
    "tokenizer.py": """
def split_fields(text):
    return text.split(';')

def parse(text):
    return split_fields(text)
"""
}


def test_supported_symbol():
    result = evaluate_static_probe(FILES, {
        "kind": "symbol_defined",
        "path": "tokenizer.py",
        "symbol": "split_fields",
        "expected_present": True,
    })
    assert result["verdict"] == "SUPPORTED"


def test_refuted_call_prediction():
    result = evaluate_static_probe(FILES, {
        "kind": "function_calls_symbol",
        "path": "tokenizer.py",
        "function": "parse",
        "symbol": "missing_function",
        "expected_present": True,
    })
    assert result["verdict"] == "REFUTED"


def test_supported_call_prediction():
    result = evaluate_static_probe(FILES, {
        "kind": "function_calls_symbol",
        "path": "tokenizer.py",
        "function": "parse",
        "symbol": "split_fields",
        "expected_present": True,
    })
    assert result["verdict"] == "SUPPORTED"


def test_missing_file_is_inconclusive():
    result = evaluate_static_probe(FILES, {
        "kind": "symbol_defined",
        "path": "missing.py",
        "symbol": "parse",
        "expected_present": True,
    })
    assert result["verdict"] == "INCONCLUSIVE"


def test_invalid_probe_is_rejected():
    with pytest.raises(HypothesisProbeError):
        evaluate_static_probe(FILES, {
            "kind": "execute_code",
            "path": "tokenizer.py",
            "symbol": "parse",
            "expected_present": True,
        })

def test_hypothesis_parser_accepts_observed_path():
    import json

    from nova.controller.hypothesis_testing import parse_hypothesis

    proposal = {
        "hypothesis": "parse delegates field splitting",
        "prediction": "parse calls split_fields",
        "probe": {
            "kind": "function_calls_symbol",
            "path": "tokenizer.py",
            "function": "parse",
            "symbol": "split_fields",
            "expected_present": True,
        },
    }
    assert parse_hypothesis(json.dumps(proposal), FILES) == proposal


def test_hypothesis_parser_rejects_unobserved_path():
    import json

    from nova.controller.hypothesis_testing import (
        HypothesisProbeError,
        parse_hypothesis,
    )

    proposal = {
        "hypothesis": "test",
        "prediction": "test",
        "probe": {
            "kind": "symbol_defined",
            "path": "secret.py",
            "function": "",
            "symbol": "parse",
            "expected_present": True,
        },
    }
    with pytest.raises(HypothesisProbeError):
        parse_hypothesis(json.dumps(proposal), FILES)


def test_response_schema_limits_paths_to_observations():
    from nova.controller.hypothesis_testing import (
        build_hypothesis_response_format,
    )

    schema = build_hypothesis_response_format(FILES)["json_schema"]["schema"]
    assert schema["properties"]["probe"]["properties"]["path"]["enum"] == [
        "tokenizer.py"
    ]


def test_hypothesis_messages_include_observed_source():
    from nova.controller.hypothesis_testing import build_hypothesis_messages

    messages = build_hypothesis_messages(
        "Fix escaped quote parsing",
        {"path": "parser.py"},
        FILES,
    )
    assert "tokenizer.py" in messages[1]["content"]


def test_hypothesis_parser_accepts_behavioral_function_call():
    import json

    from nova.controller.hypothesis_testing import parse_hypothesis

    proposal = {
        "hypothesis": "split_fields mishandles escaped quotes",
        "prediction": "The escaped quote input raises an exception",
        "probe": {
            "kind": "function_call",
            "path": "tokenizer.py",
            "function": "split_fields",
            "symbol": "",
            "expected_present": False,
            "args": [r'name="A \\"quoted; value";status=ok'],
            "kwargs": {},
            "expected_result": ["name=value", "status=ok"],
        },
    }
    parsed = parse_hypothesis(json.dumps(proposal), FILES)
    assert parsed["probe"]["kind"] == "function_call"
    assert parsed["probe"]["function"] == "split_fields"
    assert parsed["probe"]["expected_result"] == ["name=value", "status=ok"]


def test_hypothesis_parser_rejects_behavioral_probe_for_unobserved_path():
    import json

    from nova.controller.hypothesis_testing import (
        HypothesisProbeError,
        parse_hypothesis,
    )

    proposal = {
        "hypothesis": "test",
        "prediction": "test",
        "probe": {
            "kind": "function_call",
            "path": "secret.py",
            "function": "parse",
            "symbol": "",
            "expected_present": False,
            "args": [],
            "kwargs": {},
            "expected_result": None,
        },
    }
    with pytest.raises(HypothesisProbeError):
        parse_hypothesis(json.dumps(proposal), FILES)


def test_hypothesis_prompt_uses_typed_record_specification():
    from nova.controller.hypothesis_testing import build_hypothesis_messages

    messages = build_hypothesis_messages(
        task="Repair escaped quoted values.",
        proposed_action={"path": "parser.py"},
        observed_files={
            "parser.py": "def parse_record(source):\n    return {}\n"
        },
        benchmark_task_id="cross_file_dependency_001",
    )

    system = messages[0]["content"]
    assert "For CFD-001, args MUST be a one-element array" in system
    assert "each with exactly key, type, and value" in system
    assert "Never emit a serialized record string in args[0]" in system
    assert "currently observed source files before any proposed" in system
    assert "not the desired post-repair behavior" in system
    assert "update the next baseline expectation" in system


def test_hypothesis_prompt_carries_probe_contract_rejection():
    import json

    from nova.controller.hypothesis_testing import build_hypothesis_messages

    rejected = r'a=b\";c=d'
    feedback = {
        "reason": "CFD-001 escaped quotes must occur inside a quoted value.",
        "rejected_input": rejected,
    }
    messages = build_hypothesis_messages(
        task="Repair escaped quoted values.",
        proposed_action={"path": "tokenizer.py"},
        observed_files={"tokenizer.py": "def split_fields(source):\n    pass\n"},
        probe_contract_feedback=feedback,
        benchmark_task_id="cross_file_dependency_001",
    )

    payload = json.loads(messages[1]["content"])
    assert payload["probe_contract_feedback"] == {
        "reason": feedback["reason"],
        "rejected_input": rejected,
    }
    assert "Do not copy or reconstruct rejected_input" in messages[0]["content"]
    assert "typed object" in messages[0]["content"]
    assert "controller serializes the fields" in messages[0]["content"]
    assert "Never emit a serialized record string" in messages[0]["content"]


def _cfd001_hypothesis(source):
    return {
        "hypothesis": "The record tokenizer mishandles quoted values.",
        "prediction": "The function returns the predicted fields.",
        "probe": {
            "kind": "function_call",
            "path": "tokenizer.py",
            "function": "split_fields",
            "symbol": "",
            "expected_present": False,
            "args": [source],
            "kwargs": {},
            "expected_result": ["name=value"],
        },
    }


def test_cfd001_probe_contract_accepts_escaped_quotes_and_semicolons():
    import json

    from nova.controller.hypothesis_testing import parse_hypothesis

    source = r'label="A \"quoted; phrase\""; owner=Ops'
    parsed = parse_hypothesis(
        json.dumps(_cfd001_hypothesis(source)),
        FILES,
        benchmark_task_id="cross_file_dependency_001",
    )
    assert parsed["probe"]["args"] == [source]


def test_cfd001_probe_contract_handles_consecutive_backslash_parity():
    import json

    from nova.controller.hypothesis_testing import parse_hypothesis

    # Two backslashes escape each other; the following quote closes the value.
    source = r'path="A \\";status=ok'
    parsed = parse_hypothesis(
        json.dumps(_cfd001_hypothesis(source)),
        FILES,
        benchmark_task_id="cross_file_dependency_001",
    )
    assert parsed["probe"]["args"] == [source]


def test_cfd001_probe_contract_rejects_prior_malformed_probe_inputs():
    import json

    from nova.controller.hypothesis_testing import parse_hypothesis

    malformed = [
        r'a=b\";c=d',
        r'"key=value with \"quote"',
    ]

    for source in malformed:
        with pytest.raises(HypothesisProbeError):
            parse_hypothesis(
                json.dumps(_cfd001_hypothesis(source)),
                FILES,
                benchmark_task_id="cross_file_dependency_001",
            )


def test_cfd001_probe_contract_requires_a_record_argument():
    import json

    from nova.controller.hypothesis_testing import parse_hypothesis

    for args in ([], [""], ["   "], ["just a value"]):
        proposal = _cfd001_hypothesis("name=value")
        proposal["probe"]["args"] = args

        with pytest.raises(HypothesisProbeError):
            parse_hypothesis(
                json.dumps(proposal),
                FILES,
                benchmark_task_id="cross_file_dependency_001",
            )


def test_cfd001_probe_contract_does_not_change_generic_probe_validation():
    import json

    from nova.controller.hypothesis_testing import parse_hypothesis

    source = r'a=b\";c=d'
    parsed = parse_hypothesis(
        json.dumps(_cfd001_hypothesis(source)),
        FILES,
    )
    assert parsed["probe"]["args"] == [source]




def test_hypothesis_messages_include_cross_file_call_graph():
    import json

    from nova.controller.hypothesis_testing import build_hypothesis_messages

    observed = {
        "parser.py": (
            "from tokenizer import split_fields\n"
            "def parse_record(source):\n"
            "    return split_fields(source)\n"
        ),
        "tokenizer.py": (
            "def split_fields(source):\n"
            "    return source.split(';')\n"
        ),
    }

    messages = build_hypothesis_messages(
        task="Fix escaped quote parsing.",
        proposed_action={"path": "parser.py"},
        observed_files=observed,
    )

    payload = json.loads(messages[1]["content"])
    graph = payload["observed_repository_graph"]

    matching = [
        edge for edge in graph["calls"]
        if edge["source_path"] == "parser.py"
        and edge["source_symbol"] == "parse_record"
        and edge["call_expression"] == "split_fields"
    ]
    assert len(matching) == 1
    assert matching[0]["target_path"] == "tokenizer.py"
    assert matching[0]["target_symbol"] == "split_fields"
    assert matching[0]["resolution"] == "imported_symbol"

    candidates = {
        (item["path"], item["function"])
        for item in graph["probe_candidates"]
    }
    assert ("parser.py", "parse_record") in candidates
    assert ("tokenizer.py", "split_fields") in candidates

    assert "prefer that callee path and function" in messages[0]["content"]
    assert {item["path"] for item in graph["files"]} == set(observed)


def test_hypothesis_parser_accepts_expected_exception_prediction():
    import json

    from nova.controller.hypothesis_testing import parse_hypothesis

    proposal = _cfd001_hypothesis(
        r'name="A \"quoted; value\"";status=ok'
    )
    proposal["prediction"] = (
        "split_fields raises ValueError with an unterminated quote message."
    )
    proposal["probe"]["expected_result"] = None
    proposal["probe"]["expected_exception"] = {
        "type": "ValueError",
        "message": "Unterminated quoted value",
    }

    parsed = parse_hypothesis(
        json.dumps(proposal),
        FILES,
        benchmark_task_id="cross_file_dependency_001",
    )
    assert parsed["probe"]["expected_exception"] == {
        "type": "ValueError",
        "message": "Unterminated quoted value",
    }
    assert parsed["probe"]["expected_result"] is None


def test_hypothesis_response_schema_requires_exception_expectation():
    from nova.controller.hypothesis_testing import build_hypothesis_response_format

    schema = build_hypothesis_response_format(FILES)["json_schema"]["schema"]
    probe_schema = schema["properties"]["probe"]
    assert "expected_exception" in probe_schema["required"]
    assert "expected_exception" in probe_schema["properties"]

def test_cfd001_probe_contract_explains_even_backslash_embedded_quote():
    import json

    from nova.controller.hypothesis_testing import (
        HypothesisProbeError,
        parse_hypothesis,
    )

    # Two runtime backslashes leave the following quote unescaped.
    source = r'a=1;b="c\\"d;e=2'
    with pytest.raises(HypothesisProbeError, match="exactly one backslash"):
        parse_hypothesis(
            json.dumps(_cfd001_hypothesis(source)),
            FILES,
            benchmark_task_id="cross_file_dependency_001",
        )


def test_hypothesis_prompt_uses_typed_spec_instead_of_manual_json_escaping():
    from nova.controller.hypothesis_testing import build_hypothesis_messages

    messages = build_hypothesis_messages(
        task="Repair escaped quoted values.",
        proposed_action={"path": "parser.py"},
        observed_files={
            "parser.py": "def parse_record(source):\n    return {}\n"
        },
        benchmark_task_id="cross_file_dependency_001",
    )
    system = messages[0]["content"]

    assert "controller adds delimiters and escapes embedded quotes" in system
    assert "key and value are semantic strings, not serialized syntax" in system
    assert "Never emit a serialized record string in args[0]" in system
    assert "exactly one backslash immediately before it" not in system


def test_cfd001_builder_supplies_valid_typed_probe_example():
    import json

    from nova.controller.hypothesis_testing import (
        build_hypothesis_messages,
        validate_cross_file_dependency_001_input,
    )
    from nova.tools.behavioral_probe import serialize_typed_record

    messages = build_hypothesis_messages(
        task="Repair quoted values with escaped quotes and semicolons.",
        proposed_action={"path": "tokenizer.py"},
        observed_files={
            "tokenizer.py": "def split_fields(source):\n    pass\n"
        },
        benchmark_task_id="cross_file_dependency_001",
    )

    payload = json.loads(messages[1]["content"])
    example = payload["cfd001_probe_example"]
    assert example == {
        "fields": [
            {"key": "name", "type": "quoted", "value": 'A "quoted; value"'},
            {"key": "status", "type": "unquoted", "value": "ok"},
        ]
    }

    runtime_value = serialize_typed_record(example)
    validate_cross_file_dependency_001_input(runtime_value)
    assert runtime_value == r'name="A \"quoted; value\"";status=ok'
    assert "controller adds delimiters" in messages[0]["content"]
    assert "Never emit a serialized record string" in messages[0]["content"]


def test_behavioral_prediction_comes_from_structured_baseline_expectation():
    import json

    from nova.controller.hypothesis_testing import parse_hypothesis

    source = 'label="A \\"quoted; phrase\\""; owner=Ops'

    # Deliberately contradict the structured return-value expectation.
    returned = _cfd001_hypothesis(source)
    returned["prediction"] = "The function raises ValueError."
    parsed_return = parse_hypothesis(
        json.dumps(returned),
        FILES,
        benchmark_task_id="cross_file_dependency_001",
    )
    assert parsed_return["prediction"] == (
        "For the currently observed source, split_fields returns "
        "the structured expected_result."
    )

    # The exception case must also be derived deterministically.
    raised = _cfd001_hypothesis(source)
    raised["prediction"] = "The function returns a list."
    raised["probe"]["expected_result"] = None
    raised["probe"]["expected_exception"] = {
        "type": "ValueError",
        "message": "Unterminated quoted value",
    }
    parsed_raise = parse_hypothesis(
        json.dumps(raised),
        FILES,
        benchmark_task_id="cross_file_dependency_001",
    )
    assert parsed_raise["prediction"] == (
        "For the currently observed source, split_fields raises "
        "the structured expected_exception."
    )

def _dependency_probe_files(parser_source=None, tokenizer_source=None):
    if parser_source is None:
        parser_source = (
            "from tokenizer import split_fields\n"
            "def parse_record(source):\n"
            "    return split_fields(source)\n"
        )
    if tokenizer_source is None:
        tokenizer_source = (
            "def split_fields(source):\n"
            "    return source.split(';')\n"
        )
    return {
        "parser.py": parser_source,
        "tokenizer.py": tokenizer_source,
    }


def test_required_dependency_probe_target_returns_unique_imported_function():
    from nova.controller.hypothesis_testing import (
        required_dependency_probe_target,
    )

    observed = _dependency_probe_files()

    assert required_dependency_probe_target(observed, "parser.py") == {
        "path": "tokenizer.py",
        "function": "split_fields",
    }


def test_required_dependency_probe_target_accepts_dependency_write_path():
    from nova.controller.hypothesis_testing import (
        required_dependency_probe_target,
    )

    observed = _dependency_probe_files()

    assert required_dependency_probe_target(observed, "tokenizer.py") == {
        "path": "tokenizer.py",
        "function": "split_fields",
    }


def test_required_dependency_probe_target_ignores_unrelated_write_path():
    from nova.controller.hypothesis_testing import (
        required_dependency_probe_target,
    )

    assert required_dependency_probe_target(
        _dependency_probe_files(), "unrelated.py"
    ) is None


def test_required_dependency_probe_target_ignores_unresolved_call():
    from nova.controller.hypothesis_testing import (
        required_dependency_probe_target,
    )

    observed = _dependency_probe_files(
        parser_source=(
            "def parse_record(source, handler):\n"
            "    return handler(source)\n"
        ),
    )

    assert required_dependency_probe_target(observed, "parser.py") is None


def test_required_dependency_probe_target_rejects_ambiguous_module_import():
    from nova.controller.hypothesis_testing import (
        required_dependency_probe_target,
    )

    observed = _dependency_probe_files()
    observed["tokenizer/__init__.py"] = (
        "def split_fields(source):\n"
        "    return [source]\n"
    )

    assert required_dependency_probe_target(observed, "parser.py") is None


def test_required_dependency_probe_target_rejects_multiple_public_targets():
    from nova.controller.hypothesis_testing import (
        required_dependency_probe_target,
    )

    observed = {
        "parser.py": (
            "from tokenizer import split_fields\n"
            "from validator import validate_record\n"
            "def parse_record(source):\n"
            "    split_fields(source)\n"
            "    return validate_record(source)\n"
        ),
        "tokenizer.py": (
            "def split_fields(source):\n"
            "    return source.split(';')\n"
        ),
        "validator.py": (
            "def validate_record(source):\n"
            "    return source\n"
        ),
    }

    assert required_dependency_probe_target(observed, "parser.py") is None


def test_required_dependency_probe_target_rejects_private_function():
    from nova.controller.hypothesis_testing import (
        required_dependency_probe_target,
    )

    observed = _dependency_probe_files(
        parser_source=(
            "from tokenizer import _split_fields\n"
            "def parse_record(source):\n"
            "    return _split_fields(source)\n"
        ),
        tokenizer_source=(
            "def _split_fields(source):\n"
            "    return source.split(';')\n"
        ),
    )

    assert required_dependency_probe_target(observed, "parser.py") is None


def test_required_dependency_probe_target_rejects_async_function():
    from nova.controller.hypothesis_testing import (
        required_dependency_probe_target,
    )

    observed = _dependency_probe_files(
        tokenizer_source=(
            "async def split_fields(source):\n"
            "    return source.split(';')\n"
        ),
    )

    assert required_dependency_probe_target(observed, "parser.py") is None


@pytest.mark.parametrize(
    "write_path",
    ["../parser.py", r"..\parser.py", "/parser.py"],
)
def test_required_dependency_probe_target_rejects_path_traversal(write_path):
    from nova.controller.hypothesis_testing import (
        required_dependency_probe_target,
    )

    assert required_dependency_probe_target(
        _dependency_probe_files(), write_path
    ) is None


@pytest.mark.parametrize(
    "write_path",
    [r".\parser.py", r".\tokenizer.py"],
)
def test_required_dependency_probe_target_normalizes_windows_separators(
    write_path,
):
    from nova.controller.hypothesis_testing import (
        required_dependency_probe_target,
    )

    assert required_dependency_probe_target(
        _dependency_probe_files(), write_path
    ) == {
        "path": "tokenizer.py",
        "function": "split_fields",
    }



def test_cfd001_typed_probe_is_normalized_before_contract_validation():
    import json

    from nova.controller.hypothesis_testing import parse_hypothesis

    files = {"parser.py": "def parse_record(source):\n    return {}\n"}
    proposal = {
        "hypothesis": "quoted values are mishandled by the tokenizer",
        "prediction": "the unchanged parser rejects the escaped-quote record",
        "probe": {
            "kind": "function_call",
            "path": "parser.py",
            "function": "parse_record",
            "symbol": "",
            "expected_present": False,
            "args": [{
                "fields": [
                    {"key": "name", "type": "quoted", "value": 'A "quoted; value"'},
                    {"key": "status", "type": "unquoted", "value": "ok"},
                ]
            }],
            "kwargs": {},
            "expected_result": None,
            "expected_exception": {"type": "ValueError", "message": "baseline"},
        },
    }
    normalized = parse_hypothesis(
        json.dumps(proposal),
        files,
        benchmark_task_id="cross_file_dependency_001",
    )
    assert normalized["probe"]["args"] == [
        r'name="A \"quoted; value\"";status=ok'
    ]


def test_cfd001_response_schema_requires_typed_record_arguments():
    from nova.controller.hypothesis_testing import build_hypothesis_response_format

    schema = build_hypothesis_response_format(
        ["parser.py"],
        benchmark_task_id="cross_file_dependency_001",
    )["json_schema"]["schema"]
    args_schema = schema["properties"]["probe"]["properties"]["args"]
    assert args_schema["minItems"] == 1
    assert args_schema["maxItems"] == 1
    assert args_schema["items"]["required"] == ["fields"]
    assert args_schema["items"]["properties"]["fields"]["items"]["required"] == [
        "key", "type", "value"
    ]


def test_cfd001_hypothesis_prompt_uses_typed_record_example():
    import json

    from nova.controller.hypothesis_testing import build_hypothesis_messages

    files = {"parser.py": "def parse_record(source):\n    return {}\n"}
    messages = build_hypothesis_messages(
        "Fix quoted record parsing",
        {"path": "parser.py"},
        files,
        benchmark_task_id="cross_file_dependency_001",
    )
    payload = json.loads(messages[1]["content"])
    assert payload["cfd001_probe_example"]["fields"][0] == {
        "key": "name",
        "type": "quoted",
        "value": 'A "quoted; value"',
    }
    assert "Never emit a serialized record" in messages[0]["content"]


def test_non_cfd001_typed_looking_argument_is_not_serialized():
    import json

    from nova.controller.hypothesis_testing import parse_hypothesis

    typed = {
        "fields": [
            {"key": "name", "type": "quoted", "value": "ordinary dictionary"},
        ]
    }
    files = {"consumer.py": "def consume(value):\n    return value\n"}
    proposal = {
        "hypothesis": "consume accepts a structured object",
        "prediction": "the unchanged function returns its argument",
        "probe": {
            "kind": "function_call",
            "path": "consumer.py",
            "function": "consume",
            "symbol": "",
            "expected_present": False,
            "args": [typed],
            "kwargs": {},
            "expected_result": typed,
            "expected_exception": None,
        },
    }
    normalized = parse_hypothesis(json.dumps(proposal), files)
    assert normalized["probe"]["args"] == [typed]
