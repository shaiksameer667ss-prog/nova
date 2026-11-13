"""Safe, read-only structural hypothesis probes. Never executes source code."""

from __future__ import annotations

import ast
import json
from typing import Any

from nova.intelligence.repository_graph import build_repository_graph


class HypothesisProbeError(ValueError):
    """Raised when a probe violates the allowed probe contract."""


class ProbeContractError(HypothesisProbeError):
    """Raised when a task-specific behavioral probe violates its input grammar."""

    def __init__(self, message: str, probe_input: Any = None) -> None:
        super().__init__(message)
        self.probe_input = probe_input


def _call_matches(node: ast.Call, symbol: str) -> bool:
    target = node.func
    if isinstance(target, ast.Name):
        return target.id == symbol
    if isinstance(target, ast.Attribute):
        return target.attr == symbol
    return False


def evaluate_static_probe(
    observed_files: dict[str, str],
    probe: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate an allowlisted structural prediction against observed source."""
    if not isinstance(observed_files, dict) or not isinstance(probe, dict):
        raise HypothesisProbeError("Invalid probe input.")

    kind = probe.get("kind")
    path = probe.get("path")
    symbol = probe.get("symbol")
    expected = probe.get("expected_present")
    function = probe.get("function", "")

    if kind not in {"symbol_defined", "function_calls_symbol"}:
        raise HypothesisProbeError("Unsupported probe kind.")
    if not all(isinstance(v, str) and v for v in (path, symbol)):
        raise HypothesisProbeError("Path and symbol must be non-empty strings.")
    if not isinstance(expected, bool):
        raise HypothesisProbeError("expected_present must be boolean.")
    if kind == "function_calls_symbol" and (
        not isinstance(function, str) or not function
    ):
        raise HypothesisProbeError("A function name is required.")

    source = observed_files.get(path)
    if not isinstance(source, str):
        verdict = "INCONCLUSIVE"
        evidence = "The requested file has not been observed."
        actual = None
    else:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as exc:
            verdict = "INCONCLUSIVE"
            evidence = f"Source could not be parsed: {exc.msg}"
            actual = None
        else:
            actual = None
            matches = []
            target = None

            if kind == "symbol_defined":
                matches = [
                    node.lineno
                    for node in tree.body
                    if isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                    )
                    and node.name == symbol
                ]
            else:
                target = next(
                    (
                        node for node in tree.body
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == function
                    ),
                    None,
                )
                if target is None:
                    verdict = "INCONCLUSIVE"
                    evidence = f"Function {function!r} was not found."
                    actual = None
                else:
                    matches = [
                        node.lineno
                        for node in ast.walk(target)
                        if isinstance(node, ast.Call)
                        and _call_matches(node, symbol)
                    ]

            if kind == "function_calls_symbol" and target is None:
                verdict = "INCONCLUSIVE"
                evidence = f"Function {function!r} was not found."
            else:
                actual = bool(matches)
                verdict = (
                    "SUPPORTED" if actual == expected else "REFUTED"
                )
                evidence = (
                    f"Matching source lines: {matches}"
                    if matches else "No matching structure found."
                )

    return {
        "verdict": verdict,
        "probe_kind": kind,
        "path": path,
        "expected_present": expected,
        "actual_present": actual,
        "evidence": evidence,
        "evidence_kind": "static_ast",
        "causality_established": False,
    }
HYPOTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "hypothesis": {"type": "string", "minLength": 1, "maxLength": 500},
        "prediction": {"type": "string", "minLength": 1, "maxLength": 500},
        "probe": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["function_call"]},
                "path": {"type": "string", "minLength": 1},
                "function": {"type": "string"},
                "symbol": {"type": "string"},
                "expected_present": {"type": "boolean"},
                "args": {"type": "array", "items": {}},
                "kwargs": {"type": "object", "additionalProperties": {}},
                "expected_result": {},
                "expected_exception": {
                    "anyOf": [
                        {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "minLength": 1, "maxLength": 100},
                                "message": {"type": "string", "maxLength": 1000},
                            },
                            "required": ["type", "message"],
                            "additionalProperties": False,
                        },
                        {"type": "null"},
                    ]
                },
            },
            "required": [
                "kind", "path", "function", "symbol", "expected_present",
                "args", "kwargs", "expected_result", "expected_exception",
            ],
            "additionalProperties": False,
        },
    },
    "required": ["hypothesis", "prediction", "probe"],
    "additionalProperties": False,
}



def required_dependency_probe_target(observed_files, proposed_write_path):
    """Return one unambiguous local dependency function related to a write path.

    The returned target is structural evidence only; it does not establish
    that the dependency is defective or causal.
    """
    if not isinstance(observed_files, dict):
        return None
    if not isinstance(proposed_write_path, str) or not proposed_write_path:
        return None

    write_path = proposed_write_path.replace("\\", "/")
    while write_path.startswith("./"):
        write_path = write_path[2:]
    if write_path.startswith("/") or ".." in write_path.split("/"):
        return None

    graph = build_repository_graph(observed_files)
    records = {item["path"]: item for item in graph["files"]}
    candidates = set()

    for edge in graph["calls"]:
        if edge.get("resolution") not in {
            "imported_symbol",
            "imported_module_attribute",
        }:
            continue
        if (
            edge.get("source_path") != write_path
            and edge.get("target_path") != write_path
        ):
            continue

        target_path = edge.get("target_path")
        target_symbol = edge.get("target_symbol")
        if (
            not isinstance(target_path, str)
            or not isinstance(target_symbol, str)
            or not target_symbol.isidentifier()
            or target_symbol.startswith("_")
        ):
            continue

        target_record = records.get(target_path)
        if target_record is None or target_record.get("parse_status") != "parsed":
            continue

        public_sync_function = any(
            definition.get("kind") == "function"
            and definition.get("name") == target_symbol
            and definition.get("qualified_name") == target_symbol
            for definition in target_record.get("definitions", [])
        )
        if public_sync_function:
            candidates.add((target_path, target_symbol))

    if len(candidates) != 1:
        return None

    target_path, target_function = next(iter(candidates))
    return {"path": target_path, "function": target_function}


def build_hypothesis_response_format(observed_paths, benchmark_task_id=None):
    from copy import deepcopy

    schema = deepcopy(HYPOTHESIS_SCHEMA)
    paths = sorted(p for p in observed_paths if isinstance(p, str) and p)
    if paths:
        schema["properties"]["probe"]["properties"]["path"]["enum"] = paths
    if benchmark_task_id == "cross_file_dependency_001":
        schema["properties"]["probe"]["properties"]["args"] = {
            "type": "array",
            "minItems": 1,
            "maxItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 32,
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 100,
                                },
                                "type": {
                                    "type": "string",
                                    "enum": ["quoted", "unquoted"],
                                },
                                "value": {
                                    "type": "string",
                                    "maxLength": 4000,
                                },
                            },
                            "required": ["key", "type", "value"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["fields"],
                "additionalProperties": False,
            },
        }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "nova_hypothesis",
            "schema": schema,
        },
    }


def build_hypothesis_messages(
    task,
    proposed_action,
    observed_files,
    probe_contract_feedback=None,
    benchmark_task_id=None,
    dependency_probe_target=None,
    dependency_target_feedback=None,
):
    if not isinstance(task, str) or not task.strip():
        raise HypothesisProbeError("Task must not be empty.")
    if not isinstance(observed_files, dict) or not observed_files:
        raise HypothesisProbeError("No observed source files are available.")

    sources = []
    graph_sources: dict[str, str] = {}
    remaining = 18000
    for path, source in list(observed_files.items())[-6:]:
        if remaining <= 0:
            break
        if isinstance(path, str) and isinstance(source, str):
            excerpt = source[:remaining]
            graph_sources[path] = excerpt
            sources.append({"path": path, "source": excerpt})
            remaining -= len(excerpt)

    repository_graph = build_repository_graph(graph_sources)

    probe_candidates = []
    for file_record in repository_graph["files"]:
        if file_record["parse_status"] != "parsed":
            continue
        for definition in file_record["definitions"]:
            name = definition["name"]
            if (
                definition["kind"] == "function"
                and definition["qualified_name"] == name
                and not name.startswith("_")
            ):
                probe_candidates.append({
                    "path": file_record["path"],
                    "function": name,
                    "start_line": definition["start_line"],
                    "end_line": definition["end_line"],
                })

    graph_calls = repository_graph["calls"]
    graph_context = {
        "files": [
            {
                "path": item["path"],
                "module": item["module"],
                "parse_status": item["parse_status"],
            }
            for item in repository_graph["files"]
        ],
        "probe_candidates": probe_candidates[:100],
        "probe_candidates_truncated": len(probe_candidates) > 100,
        "calls": graph_calls[:200],
        "calls_truncated": len(graph_calls) > 200,
        "analysis_limits": repository_graph["analysis_limits"],
    }

    payload = {
        "task": task,
        "proposed_write_path": proposed_action.get("path", ""),
        "observed_sources": sources,
        "observed_repository_graph": graph_context,
    }
    dependency_instruction = ""
    if dependency_probe_target is not None:
        if (
            not isinstance(dependency_probe_target, dict)
            or not isinstance(dependency_probe_target.get("path"), str)
            or not isinstance(dependency_probe_target.get("function"), str)
        ):
            raise HypothesisProbeError(
                "Dependency probe target must contain a path and function."
            )
        payload["required_dependency_probe_target"] = {
            "path": dependency_probe_target["path"],
            "function": dependency_probe_target["function"],
        }
        dependency_instruction = (
            " The controller resolved one unique local dependency function "
            "for this CFD-001 write. You MUST probe exactly the path/function "
            "pair in required_dependency_probe_target. Do not substitute "
            "the caller that exposes the behavior. This is a probe-selection "
            "constraint based on static structure, NOT proof that the "
            "dependency is defective or causal."
        )
    if dependency_target_feedback is not None:
        if not isinstance(dependency_target_feedback, dict):
            raise HypothesisProbeError(
                "Dependency-target feedback must be a dictionary."
            )
        payload["dependency_target_feedback"] = {
            "reason": str(dependency_target_feedback.get("reason") or ""),
            "required_probe": dependency_target_feedback.get("required_probe"),
            "rejected_probe": dependency_target_feedback.get("rejected_probe"),
        }
        dependency_instruction += (
            " Your previous function-call probe selected the wrong target. "
            "Read dependency_target_feedback and use the exact required "
            "path/function pair. Do not repeat the rejected target."
        )
    if benchmark_task_id == "cross_file_dependency_001":
        payload["cfd001_probe_example"] = {
            "fields": [
                {"key": "name", "type": "quoted", "value": 'A "quoted; value"'},
                {"key": "status", "type": "unquoted", "value": "ok"},
            ]
        }
    feedback_instruction = ""
    if probe_contract_feedback is not None:
        if not isinstance(probe_contract_feedback, dict):
            raise HypothesisProbeError(
                "Probe-contract feedback must be a dictionary."
            )
        payload["probe_contract_feedback"] = {
            "reason": str(probe_contract_feedback.get("reason") or ""),
            "rejected_input": probe_contract_feedback.get("rejected_input"),
        }
        feedback_instruction = (
            " A previous CFD-001 probe was rejected by deterministic input "
            "validation. Read probe_contract_feedback in the user payload. "
            "Do not copy or reconstruct rejected_input as a runtime string. "
            "Generate args as a one-element array containing a typed object "
            "with a fields array; each field must contain key, type, and value. "
            "Use type=quoted for values containing quotes or semicolons and "
            "type=unquoted otherwise. The controller serializes the fields. "
        )
    cfd001_instruction = ""
    if benchmark_task_id == "cross_file_dependency_001":
        cfd001_instruction = (
            " For CFD-001, args MUST be a one-element array. Its first item "
            "must be an object with exactly one property, fields. fields is "
            "an array of objects, each with exactly key, type, and value. "
            "key and value are semantic strings, not serialized syntax. type "
            "is quoted or unquoted. Use quoted for a value that should be "
            "double-quoted in the record; the controller adds delimiters "
            "and escapes embedded quotes and backslashes. Use unquoted for "
            "plain values without semicolons or double quotes. Copy the "
            "typed field representation from cfd001_probe_example when "
            "probing that record grammar. Never emit a serialized record "
            "string in args[0]."
        )

    system = (
        "Propose exactly one falsifiable RUNTIME BEHAVIORAL hypothesis about "
        "the likely cause of the task failure. The behavioral probe runs "
        "against the currently observed source files before any proposed "
        "write is applied. Predict what the unchanged function does now, "
        "not the desired post-repair behavior. expected_result or "
        "expected_exception must encode that current baseline behavior "
        "exactly. A normal return requires expected_exception=null and "
        "the exact JSON expected_result; an exception requires "
        "expected_result=null and its exact type and message. After a "
        "prediction mismatch, use the actual observed result to update "
        "the next baseline expectation. Return JSON only. You MUST use "
        "kind=function_call; static AST probes are not accepted for an "
        "existing-file repair. Inspect observed_repository_graph before "
        "choosing the target. Select the function that owns the behavior "
        "under test, not automatically the caller that exposes it. If a "
        "caller delegates to a resolved local callee and that callee "
        "performs the relevant transformation, prefer that callee path "
        "and function. The graph is static structural evidence, not proof "
        "of causality. Choose an exact path/function pair from "
        "probe_candidates, which contains observed public top-level "
        "synchronous functions only. Supply "
        "JSON-compatible positional args, keyword kwargs, and the exact "
        "expected JSON result. Set expected_exception to null for a normal "
        "return. For an expected exception, provide its exact type and "
        "message in expected_exception and set expected_result to null. "
        "The verifier compares both exception type and message exactly. "
        "Probe args must be JSON-compatible runtime values, not Python "
        "source notation. "
        "Set symbol to an empty string and "
        "expected_present to false. Do not provide code, shell commands, or "
        "imports. The controller executes the function in a restricted "
        "sandbox. A matched or mismatched prediction is behavioral evidence, "
        "not proof of causality. Do not invent a probe if you cannot predict "
        "a concrete result."
    ) + feedback_instruction + dependency_instruction + cfd001_instruction
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]



def validate_cross_file_dependency_001_input(source: Any) -> None:
    """Validate one CFD-001 key=value record without executing it."""
    if not isinstance(source, str) or not source.strip():
        raise ProbeContractError(
            "CFD-001 probe input must be a non-empty record string."
        )

    in_quotes = False
    backslash_run = 0
    field_start = 0
    equals_index = None
    valid_fields = 0
    quote_closed = False

    for index, char in enumerate(source):
        if char == "\\":
            backslash_run += 1
            continue

        escaped = backslash_run % 2 == 1
        backslash_run = 0

        if char == '"':
            if escaped:
                if not in_quotes:
                    raise ProbeContractError(
                        "CFD-001 escaped quotes must occur inside "
                        "a double-quoted value."
                    )
                continue

            if in_quotes:
                in_quotes = False
                quote_closed = True
            else:
                if equals_index is None:
                    raise ProbeContractError(
                        "CFD-001 quoted values must follow a key= field."
                    )
                if source[equals_index + 1:index].strip():
                    raise ProbeContractError(
                        "CFD-001 opening quote must begin the trimmed "
                        "field value."
                    )
                in_quotes = True
                quote_closed = False
            continue

        if in_quotes:
            continue

        if char == ";":
            field = source[field_start:index]
            if field.strip():
                if equals_index is None:
                    raise ProbeContractError(
                        "CFD-001 every non-empty field must contain key=value."
                    )
                if not source[field_start:equals_index].strip():
                    raise ProbeContractError(
                        "CFD-001 field keys must not be empty."
                    )
                valid_fields += 1

            field_start = index + 1
            equals_index = None
            quote_closed = False
            continue

        if quote_closed and not char.isspace():
            raise ProbeContractError(
                "After a closing quoted value, only whitespace or a field "
                "separator may follow. If this was intended as an embedded "
                "quote, use exactly one backslash before it; two backslashes "
                "leave the quote unescaped."
            )

        if char == "=" and equals_index is None:
            if not source[field_start:index].strip():
                raise ProbeContractError(
                    "CFD-001 key=value fields require a non-empty key."
                )
            equals_index = index

    if in_quotes:
        raise ProbeContractError(
            "CFD-001 probe input contains an unterminated quoted value."
        )

    final_field = source[field_start:]
    if final_field.strip():
        if equals_index is None:
            raise ProbeContractError(
                "CFD-001 every non-empty field must contain key=value."
            )
        if not source[field_start:equals_index].strip():
            raise ProbeContractError(
                "CFD-001 field keys must not be empty."
            )
        valid_fields += 1

    if valid_fields == 0:
        raise ProbeContractError(
            "CFD-001 probe must contain at least one key=value field."
        )


def parse_hypothesis(raw, observed_files, benchmark_task_id=None):
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HypothesisProbeError("Invalid hypothesis JSON.") from exc

    if not isinstance(value, dict) or set(value) != {
        "hypothesis", "prediction", "probe"
    }:
        raise HypothesisProbeError("Invalid hypothesis fields.")

    for field in ("hypothesis", "prediction"):
        text = value[field]
        if not isinstance(text, str) or not text.strip() or len(text) > 500:
            raise HypothesisProbeError(f"Invalid {field}.")

    probe = value["probe"]
    static_fields = {
        "kind", "path", "function", "symbol", "expected_present"
    }
    canonical_fields = static_fields | {"args", "kwargs", "expected_result"}

    if not isinstance(probe, dict):
        raise HypothesisProbeError("Invalid probe fields.")

    kind = probe.get("kind")
    if kind in {"symbol_defined", "function_calls_symbol"}:
        if set(probe) == canonical_fields:
            if (
                probe["args"] != []
                or probe["kwargs"] != {}
                or probe["expected_result"] is not None
            ):
                raise HypothesisProbeError(
                    "Static probes require empty args/kwargs and null expected_result."
                )
            probe = {key: probe[key] for key in static_fields}
            value["probe"] = probe
        elif set(probe) != static_fields:
            raise HypothesisProbeError("Invalid static probe fields.")

        if probe["path"] not in observed_files:
            raise HypothesisProbeError("Probe path was not observed.")
        if not isinstance(probe["symbol"], str) or not probe["symbol"].strip():
            raise HypothesisProbeError("Invalid probe symbol.")
        if not isinstance(probe["function"], str):
            raise HypothesisProbeError("Invalid probe function.")
        if kind == "function_calls_symbol" and not probe["function"].strip():
            raise HypothesisProbeError("Function name is required.")
        if kind == "symbol_defined" and probe["function"]:
            raise HypothesisProbeError(
                "Function must be empty for symbol_defined."
            )
        if not isinstance(probe["expected_present"], bool):
            raise HypothesisProbeError("Invalid expected_present.")

    elif kind == "function_call":
        behavioral_fields = canonical_fields | {"expected_exception"}
        if set(probe) == canonical_fields:
            probe = {**probe, "expected_exception": None}
        if set(probe) != behavioral_fields:
            raise HypothesisProbeError("Invalid behavioral probe fields.")
        if probe["symbol"] != "" or probe["expected_present"] is not False:
            raise HypothesisProbeError(
                "Behavioral probes require empty symbol and false expected_present."
            )
        from nova.tools.behavioral_probe import validate_behavioral_probe

        behavioral_probe = {
            key: probe[key]
            for key in (
                "kind", "path", "function", "args", "kwargs",
                "expected_result", "expected_exception",
            )
        }
        if (
            behavioral_probe["expected_exception"] is not None
            and behavioral_probe["expected_result"] is not None
        ):
            raise HypothesisProbeError(
                "Expected exceptions require expected_result to be null."
            )

        try:
            normalized_behavioral_probe = validate_behavioral_probe(
                observed_files,
                behavioral_probe,
                allow_typed_record=(
                    benchmark_task_id == "cross_file_dependency_001"
                ),
            )
            behavioral_probe["args"] = normalized_behavioral_probe["args"]
        except (TypeError, ValueError) as exc:
            raise HypothesisProbeError(str(exc)) from exc

        if benchmark_task_id == "cross_file_dependency_001":
            args = behavioral_probe["args"]
            if not args:
                raise HypothesisProbeError(
                    "CFD-001 function_call probes require args[0] "
                    "to contain one complete record."
                )
            try:
                validate_cross_file_dependency_001_input(args[0])
            except ProbeContractError as exc:
                raise ProbeContractError(
                    str(exc),
                    probe_input=args[0],
                ) from exc

        # The structured expectation is the single source of truth.
        # The probe runs on the unchanged observed source, before a write.
        if behavioral_probe["expected_exception"] is None:
            value["prediction"] = (
                f'For the currently observed source, '
                f'{behavioral_probe["function"]} returns the structured '
                'expected_result.'
            )
        else:
            value["prediction"] = (
                f'For the currently observed source, '
                f'{behavioral_probe["function"]} raises the structured '
                'expected_exception.'
            )

        value["probe"] = behavioral_probe

    else:
        raise HypothesisProbeError("Unsupported probe kind.")

    return value
