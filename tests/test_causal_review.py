import json

import pytest

from nova.controller.causal_review import (
    CausalReviewError,
    build_causal_review_response_format,
    build_prewrite_review_messages,
    discover_observed_dependencies,
    parse_prewrite_review,
)

OBSERVED = {
    "parser.py": "from tokenizer import split_fields\n\ndef parse_record(source): ...",
    "tokenizer.py": 'if char == "\\"":\n    in_quotes = not in_quotes',
}


def review(**overrides):
    value = {
        "decision": "REVISE",
        "root_cause": "The tokenizer mishandles escaped quotes.",
        "causal_chain": [
            "The parser imports split_fields from tokenizer.",
            "The tokenizer toggles quote state on every quote character.",
            "The semicolon is consequently treated as a field separator.",
        ],
        "evidence": [
            {
                "path": "parser.py",
                "start_line": 1,
                "end_line": 1,
            },
        ],
        "repair_target": "tokenizer.py",
        "guidance": "Correct quote-state handling in tokenizer.py.",
    }
    value.update(overrides)
    return json.dumps(value)


def test_build_review_includes_plan_proposal_and_observations():
    observed = {
        'parser.py': 'from tokenizer import split_fields\n\ndef parse_record(source):\n    return split_fields(source)\n',
        'tokenizer.py': 'def split_fields(source: str) -> list[str]:\n    fields = []\n    start = 0\n    in_quotes = False\n    for index, char in enumerate(source):\n        if char == \'"\':\n            in_quotes = not in_quotes\n        elif char == \';\' and not in_quotes:\n            fields.append(source[start:index].strip())\n            start = index + 1\n    fields.append(source[start:].strip())\n    return fields\n',
    }
    messages = build_prewrite_review_messages(
        'Fix parser behavior.',
        {'objective': 'Correct parsing'},
        {
            'action': 'write_file',
            'path': 'parser.py',
            'content': 'new parser content',
        },
        observed,
    )

    context = json.loads(messages[1]['content'])
    assert context['task'] == 'Fix parser behavior.'
    assert context['proposed_write']['path'] == 'parser.py'
    assert context['proposed_write']['content'] == 'new parser content'
    assert {
        item['path'] for item in context['successful_file_observations']
    } == {'parser.py', 'tokenizer.py'}

    edges = context['observed_dependency_edges']
    assert len(edges) == 1
    edge = edges[0]
    assert edge['importer_path'] == 'parser.py'
    assert edge['dependency_path'] == 'tokenizer.py'
    assert edge['imported_names'] == ['split_fields']
    assert edge['used_imported_names'] == ['split_fields']
    assert edge['import_statement'] == 'from tokenizer import split_fields'
    definitions = edge['dependency_definitions']
    assert len(definitions) == 1
    assert definitions[0]['name'] == 'split_fields'
    assert 'in_quotes = not in_quotes' in definitions[0]['source']


def test_review_accepts_evidence_backed_revision():
    parsed = parse_prewrite_review(
        review(),
        OBSERVED,
        "parser.py",
    )

    assert parsed["decision"] == "REVISE"
    assert parsed["repair_target"] == "tokenizer.py"


def test_review_approves_only_matching_repair_target():
    approved = review(
        decision="APPROVE",
        repair_target="parser.py",
        guidance="The parser change addresses the supported cause.",
    )

    parsed = parse_prewrite_review(approved, OBSERVED, "parser.py")
    assert parsed["decision"] == "APPROVE"


def test_approval_for_different_file_is_rejected():
    approved = review(
        decision="APPROVE",
        repair_target="tokenizer.py",
    )

    with pytest.raises(CausalReviewError, match="must match"):
        parse_prewrite_review(approved, OBSERVED, "parser.py")


def test_fabricated_evidence_is_rejected():
    fabricated = review(
        evidence=[{
            "path": "tokenizer.py",
            "start_line": 99,
            "end_line": 99,
        }]
    )

    with pytest.raises(CausalReviewError, match="outside observed source"):
        parse_prewrite_review(fabricated, OBSERVED, "parser.py")


def test_approval_without_evidence_is_rejected():
    unsupported = review(
        decision="APPROVE",
        repair_target="parser.py",
        evidence=[],
    )

    with pytest.raises(CausalReviewError, match="requires exact source evidence"):
        parse_prewrite_review(unsupported, OBSERVED, "parser.py")


def test_investigation_decision_can_request_more_information():
    response = review(
        decision="INVESTIGATE",
        root_cause="The root cause is not established.",
        evidence=[],
        repair_target="",
        guidance="Read the imported tokenizer implementation first.",
    )

    parsed = parse_prewrite_review(response, OBSERVED, "parser.py")
    assert parsed["decision"] == "INVESTIGATE"


def test_review_rejects_invalid_json():
    with pytest.raises(CausalReviewError, match="Invalid review JSON"):
        parse_prewrite_review("{bad json}", OBSERVED, "parser.py")


def test_review_rejects_non_write_action():
    with pytest.raises(ValueError, match="requires a write_file"):
        build_prewrite_review_messages(
            "Task",
            {},
            {"action": "read_file", "path": "parser.py"},
            OBSERVED,
        )

def test_response_schema_constrains_evidence_to_exact_observed_paths():
    response_format = build_causal_review_response_format(
        ["parser.py", "tokenizer.py"],
        "parser.py",
    )
    schema = response_format["json_schema"]["schema"]
    allowed_evidence = schema["properties"]["evidence"]["items"]["properties"]["path"]["enum"]
    allowed_targets = schema["properties"]["repair_target"]["enum"]
    evidence_item = schema["properties"]["evidence"]["items"]
    assert evidence_item["required"] == [
        "path", "start_line", "end_line"
    ]

    assert allowed_evidence == ["parser.py", "tokenizer.py"]
    assert set(allowed_targets) == {"", "parser.py", "tokenizer.py"}


def test_revise_target_must_be_an_observed_file():
    response = review(repair_target="uninspected.py")

    with pytest.raises(CausalReviewError, match="exactly observed"):
        parse_prewrite_review(response, OBSERVED, "parser.py")


def test_dependency_analyzer_finds_imported_and_called_local_function():
    observed = {
        "parser.py": (
            "from tokenizer import split_fields\n\n"
            "def parse_record(source):\n"
            "    return split_fields(source)\n"
        ),
        "tokenizer.py": (
            "def split_fields(source):\n"
            "    return source.split(';')\n"
        ),
    }

    edges = discover_observed_dependencies(observed)

    assert len(edges) == 1
    edge = edges[0]
    assert edge["importer_path"] == "parser.py"
    assert edge["dependency_path"] == "tokenizer.py"
    assert edge["module"] == "tokenizer"
    assert edge["imported_names"] == ["split_fields"]
    assert edge["used_imported_names"] == ["split_fields"]
    assert edge["import_statement"] == (
        "from tokenizer import split_fields"
    )
    assert edge["dependency_definitions"][0]["name"] == "split_fields"
    assert "return source.split(';')" in (
        edge["dependency_definitions"][0]["source"]
    )


def test_dependency_analyzer_ignores_unobserved_external_modules():
    observed = {
        "parser.py": (
            "import ast\n"
            "from external_package import helper\n"
        ),
    }

    assert discover_observed_dependencies(observed) == []


def test_reviewer_prompt_requires_diagnostic_only_guidance():
    messages = build_prewrite_review_messages(
        "Fix parser behavior.",
        {"objective": "Correct parsing"},
        {
            "action": "write_file",
            "path": "parser.py",
            "content": "def parse_record(source):\n    return {}",
        },
        OBSERVED,
    )

    prompt = messages[0]["content"].lower()
    assert "diagnostic-only" in prompt
    assert "do not prescribe an implementation pattern" in prompt
    assert "do not include code, pseudocode" in prompt


def test_review_rejects_implementation_prescriptive_guidance():
    recipes = [
        r"""if index > 0 and source[index - 1] == '\\': continue""",
        (
            "Check whether the previous character is a backslash "
            "before toggling quote state."
        ),
    ]

    for guidance in recipes:
        with pytest.raises(CausalReviewError, match="diagnostic-only"):
            parse_prewrite_review(
                review(guidance=guidance),
                OBSERVED,
                "parser.py",
            )


def test_review_accepts_observable_behavior_guidance():
    guidance = (
        "The tokenizer treats escaped quotes as delimiters, which causes "
        "semicolons inside quoted values to be split. Correct behavior "
        "preserves escaped quotes within the value and keeps embedded "
        "semicolons inside that field."
    )

    parsed = parse_prewrite_review(
        review(guidance=guidance),
        OBSERVED,
        "parser.py",
    )

    assert parsed["guidance"] == guidance



def test_prewrite_review_includes_observed_static_call_graph():
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
    messages = build_prewrite_review_messages(
        "Fix parser behavior.",
        {"objective": "Correct parsing"},
        {
            "action": "write_file",
            "path": "parser.py",
            "content": "new parser content",
        },
        observed,
    )

    context = json.loads(messages[1]["content"])
    graph = context["observed_repository_graph"]

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

    tokenizer = next(
        item for item in graph["files"]
        if item["path"] == "tokenizer.py"
    )
    assert tokenizer["definitions"][0]["qualified_name"] == "split_fields"
    assert "static source analysis only" in graph["analysis_limits"][0].lower()

def test_prewrite_review_separates_probe_evidence_from_execution_plan():
    plan = {"objective": "Correct parsing"}
    prior_reviews = [{"decision": "INVESTIGATE"}]
    evidence = {
        "hypothesis": "The parser may report a tokenizer failure.",
        "prediction": "Normalized structured expectation.",
        "probe": {
            "kind": "function_call",
            "path": "parser.py",
            "function": "parse_record",
            "args": ['name="A \\"quoted; value\\"";status=ok'],
            "kwargs": {},
            "expected_result": None,
            "expected_exception": {
                "type": "ValueError",
                "message": "Invalid quoted value",
            },
        },
        "probe_result": {
            "verdict": "PREDICTION_MATCHED",
            "probe_completed": True,
            "evidence_kind": "sandbox_execution",
            "actual_exception": {
                "type": "ValueError",
                "message": "Invalid quoted value",
            },
            "causality_established": False,
        },
    }
    review_context = {
        "execution_plan": plan,
        "prior_causal_reviews": prior_reviews,
        "hypothesis_test": evidence,
    }

    messages = build_prewrite_review_messages(
        "Fix parser behavior.",
        review_context,
        {
            "action": "write_file",
            "path": "parser.py",
            "content": "new parser content",
        },
        OBSERVED,
    )

    context = json.loads(messages[1]["content"])
    prompt = messages[0]["content"].lower()

    assert context["current_plan"] == plan
    assert context["prior_causal_reviews"] == prior_reviews
    assert context["behavioral_evidence"] == evidence
    assert "hypothesis_test" not in context["current_plan"]
    assert "behavioral_evidence.probe_result" in prompt
    assert "does not, by itself, establish causality" in prompt
    assert "choose investigate" in prompt

def test_build_review_includes_proposed_diff():
    """V4 regression: reviewer must receive before/after diff, not just current file."""
    import json as _json

    from nova.controller.causal_review import build_prewrite_review_messages

    before = 'def split_fields(s):\n    return s.split(";")\n'
    after  = 'def split_fields(s):\n    # parity-aware fix\n    return s.split(";")\n'

    messages = build_prewrite_review_messages(
        "fix split_fields",
        {},
        {"action": "write_file", "path": "tokenizer.py", "content": after},
        {"tokenizer.py": before, "parser.py": "from tokenizer import split_fields\n"},
    )

    context = _json.loads(messages[1]["content"])
    assert "proposed_diff" in context, "reviewer context must contain proposed_diff"
    diff = context["proposed_diff"]
    assert diff["path"] == "tokenizer.py"
    assert diff["before_write"] == before
    assert diff["after_write"] == after
    assert diff["change_kind"] == "modification"
    assert "before_write" in diff["evaluate_rule"]
    assert "after_write" in diff["evaluate_rule"]

    prompt = messages[0]["content"]
    assert "Primary evaluation" in prompt
    assert prompt.index("Primary evaluation") < prompt.index("Reasoning requirements:")


def test_build_review_proposed_diff_change_kinds():
    """V4 regression: change_kind distinguishes new_file, no_op, modification."""
    import json as _json

    from nova.controller.causal_review import build_prewrite_review_messages

    # new_file: path not in observed_files
    messages = build_prewrite_review_messages(
        "add new module",
        {},
        {"action": "write_file", "path": "new.py", "content": "x = 1\n"},
        {"tokenizer.py": "def split_fields(s):\n    return s.split(';')\n"},
    )
    context = _json.loads(messages[1]["content"])
    assert context["proposed_diff"]["change_kind"] == "new_file"
    assert context["proposed_diff"]["before_write"] == ""

    # no_op: content identical to observed
    identical = 'def split_fields(s):\n    return s.split(";")\n'
    messages = build_prewrite_review_messages(
        "fix split_fields",
        {},
        {"action": "write_file", "path": "tokenizer.py", "content": identical},
        {"tokenizer.py": identical},
    )
    context = _json.loads(messages[1]["content"])
    assert context["proposed_diff"]["change_kind"] == "no_op"

    # modification: content differs
    messages = build_prewrite_review_messages(
        "fix split_fields",
        {},
        {"action": "write_file", "path": "tokenizer.py", "content": "def split_fields(s):\n    return s.split(';')\n"},
        {"tokenizer.py": identical},
    )
    context = _json.loads(messages[1]["content"])
    assert context["proposed_diff"]["change_kind"] == "modification"
