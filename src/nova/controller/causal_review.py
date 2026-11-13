"""Evidence-grounded review of proposed modifications to existing files."""

from __future__ import annotations

import ast
import json
import re
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any

from nova.intelligence.repository_graph import build_repository_graph


class CausalReviewError(ValueError):
    """Raised when a causal review response is invalid or unsupported."""


CAUSAL_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["APPROVE", "REVISE", "INVESTIGATE"],
        },
        "root_cause": {
            "type": "string",
            "minLength": 1,
            "maxLength": 600,
        },
        "causal_chain": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 400,
            },
        },
        "evidence": {
            "type": "array",
            "minItems": 0,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                "required": ["path", "start_line", "end_line"],
                "additionalProperties": False,
            },
        },
        "repair_target": {
            "type": "string",
            "maxLength": 500,
        },
        "guidance": {
            "type": "string",
            "minLength": 1,
            "maxLength": 1200,
        },
    },
    "required": [
        "decision",
        "root_cause",
        "causal_chain",
        "evidence",
        "repair_target",
        "guidance",
    ],
    "additionalProperties": False,
}

CAUSAL_REVIEW_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "nova_causal_prewrite_review",
        "schema": CAUSAL_REVIEW_SCHEMA,
    },
}


def build_causal_review_response_format(
    observed_paths: Any,
    proposed_path: str,
) -> dict:
    """Constrain reviewer paths to exact observed paths and proposed target."""
    paths = sorted({
        path for path in observed_paths
        if isinstance(path, str) and path
    })
    schema = deepcopy(CAUSAL_REVIEW_SCHEMA)

    if paths:
        schema["properties"]["evidence"]["items"]["properties"]["path"][
            "enum"
        ] = paths

    schema["properties"]["repair_target"]["enum"] = sorted(
        {"", proposed_path, *paths}
    )

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "nova_causal_prewrite_review",
            "schema": schema,
        },
    }

CAUSAL_REVIEW_SYSTEM_PROMPT = """You are NOVA's evidence-grounded pre-write reviewer.

Your job is to challenge a proposed code modification before it is executed.

You receive:
- The task and current execution plan.
- The proposed write path and complete proposed content.
- Source files that NOVA has successfully read from its workspace.
- Behavioral evidence, including the proposed probe, expected outcome,
  and actual sandbox observation.
- Prior causal-review decisions, when available.

Behavioral evidence requirements:
1. Treat behavioral_evidence.probe as the model's expected behavior,
   not as an observed runtime result.
2. Treat behavioral_evidence.probe_result as the actual sandbox
   observation. Use its actual_result or actual_exception fields to
   establish what happened during execution.
3. A prediction match establishes that the actual outcome matched the
   structured expectation. It does not, by itself, establish causality.
4. Trace the exact probe input through the observed function and its
   relevant dependencies. Identify where the actual data flow first
   departs from the task's required behavior.
5. Distinguish the function where an exception becomes visible from
   the component that produces the incorrect behavior.
6. If the observations do not isolate a defective component, choose
   INVESTIGATE rather than asserting an unsupported root cause.
7. Use prior causal reviews as history, not as proof. Repeated
   agreement between reviews does not replace source or runtime evidence.

Determine whether the proposed modification addresses the actual cause
of the observed problem, rather than merely changing the file where a
symptom appears.

Primary evaluation (perform this before any other reasoning):

1. Read proposed_diff.before_write and proposed_diff.after_write.
2. The successful_file_observations for the proposed path reflect the
   PRE-WRITE state. That state is what motivated the repair; do not
   describe it again as the defect. The defect has been diagnosed.
3. Instead, describe the change from before_write to after_write.
4. Evaluate whether after_write resolves the diagnosed defect. If it
   does, APPROVE. If after_write still exhibits the defect, REVISE.
5. Do not prescribe an implementation algorithm. Evaluate the supplied
   content only.

Reasoning requirements:
1. Trace relevant imports, function calls, data flow, and dependencies
   across the observed files.
1a. Treat observed_dependency_edges as verified structural facts.
    Inspect the supplied implementation of imported functions.
1b. Do not assume a dependency is correct merely because its docstring
    describes the intended behavior. Examine its actual implementation.
1c. Compare dependency behavior with every relevant task constraint,
    especially escaping, state transitions, and boundary conditions.
1d. Treat observed_repository_graph as static structural evidence derived only from source excerpts shown in successful_file_observations.
    Use resolved call edges and qualified definitions to trace behavior across files and identify the implementation that owns it.
    A resolved call edge establishes a syntactic target, not causality.
    An unresolved edge means static analysis could not resolve the target; it does not prove that no dependency exists.
2. Distinguish the component producing incorrect behavior from the
   component where an error becomes visible.
3. Compare the proposed modification with the evidence and task contract.
4. Consider whether the modification preserves required behavior.
5. Do not assume that a proposed patch is correct because it is plausible.
6. Do not invent source code, observations, tests, or execution results.
7. Evidence entries must contain path, start_line, and end_line.
   Line numbers are 1-based and inclusive, as shown in the numbered
   successful_file_observations.
8. Select line ranges that directly support your reasoning. Do not
   generate or reproduce source quotations yourself.
9. Each evidence.path must exactly match allowed_evidence_paths.
10. The proposed patch is not source evidence.
11. For REVISE, repair_target must be an exact path in
    allowed_repair_targets and that file must have been observed.
    If the likely target has not been inspected, choose INVESTIGATE.

Guidance contract (mandatory):
1. Guidance must be diagnostic-only. State which observed component is
   defective, what incorrect behavior it produces, and what observable
   behavior the corrected component must produce.
2. Do not prescribe an implementation pattern, algorithm, data structure,
   variable, condition, loop, index calculation, escape-state mechanism,
   or sequence of code edits.
3. Do not include code, pseudocode, source expressions, or code examples.
   NOVA is responsible for choosing and implementing the correction from
   the task contract and observed evidence.
4. For INVESTIGATE, guidance may identify the specific missing observation
   or dependency NOVA should inspect, but must not prescribe code.

Additional precision for REVISE guidance:
5. Describe only the defective observed component, its incorrect observable behavior, and the required observable behavior.
6. Do not tell NOVA which character to inspect, which condition to check, how to track state, or what sequence of operations to implement.
7. Example of forbidden prescriptive guidance: 'Check the preceding character for a backslash before toggling quote state.'
8. Example of acceptable diagnostic-only guidance: 'The tokenizer treats escaped quotes as delimiters. Correct behavior preserves escaped quotes within quoted values and keeps embedded semicolons within the same field.'
9. Use the acceptable example only when supported by the observed source and behavioral evidence; do not assume its diagnosis.

Choose exactly one decision:

APPROVE:
Use only when the proposed file is a defensible repair target and the
proposed modification addresses the supported cause. At least one exact
source quotation is required. repair_target must equal the proposed path.

REVISE:
Use when the proposed repair is aimed at the wrong component or does not
address the supported cause. Identify the better repair target when known.
Provide valid source line ranges and diagnostic-only guidance.

INVESTIGATE:
Use when the observations are insufficient or ambiguous. State what
information is missing and what NOVA should inspect next. Do not approve
an unsupported modification.

Be conservative. An uncertain review must not approve a write.

Return JSON only, matching the supplied schema.
"""


def build_prewrite_review_messages(
    task: str,
    current_plan: dict[str, Any],
    proposed_action: dict[str, Any],
    observed_files: dict[str, str],
) -> list[dict[str, str]]:
    """Build a bounded review request from successful workspace observations."""
    if not isinstance(task, str) or not task.strip():
        raise ValueError("Task must not be empty.")

    if not isinstance(proposed_action, dict):
        raise TypeError("Proposed action must be a dictionary.")

    if proposed_action.get("action") != "write_file":
        raise ValueError("Causal review requires a write_file action.")

    path = proposed_action.get("path")
    content = proposed_action.get("content")

    if not isinstance(path, str) or not path.strip():
        raise ValueError("Proposed write path must not be empty.")

    if not isinstance(content, str):
        raise TypeError("Proposed write content must be a string.")

    if not isinstance(observed_files, dict):
        raise TypeError("Observed files must be a dictionary.")

    # Bound reviewer context to six files and 18,000 source characters.
    observations = []
    remaining = 18000
    graph_sources: dict[str, str] = {}

    for observed_path, source in list(observed_files.items())[-6:]:
        if remaining <= 0:
            break
        if not isinstance(observed_path, str) or not isinstance(source, str):
            continue

        excerpt = source[:remaining]
        graph_sources[observed_path] = excerpt
        numbered_excerpt = "\\n".join(
            f"{line_number:>4}: {line}"
            for line_number, line in enumerate(excerpt.splitlines(), start=1)
        )
        observations.append({
            "path": observed_path,
            "content": numbered_excerpt,
            "visible_line_count": len(excerpt.splitlines()),
            "truncated": len(excerpt) < len(source),
        })
        remaining -= len(excerpt)

    dependency_edges = discover_observed_dependencies(graph_sources)
    repository_graph = build_repository_graph(
        graph_sources,
        imports=dependency_edges,
    )

    review_context = current_plan
    execution_plan = review_context.get("execution_plan", review_context)
    prior_causal_reviews = review_context.get("prior_causal_reviews", [])
    behavioral_evidence = review_context.get("hypothesis_test")

    context = {
        "task": task,
        "current_plan": execution_plan,
        "prior_causal_reviews": prior_causal_reviews,
        "behavioral_evidence": behavioral_evidence,
        "proposed_write": {
            "path": path,
            "content": content[:12000],
            "truncated": len(content) > 12000,
        },
        "successful_file_observations": observations,
        "observed_dependency_edges": dependency_edges,
        "observed_repository_graph": {
            "files": repository_graph["files"],
            "calls": repository_graph["calls"],
            "analysis_limits": repository_graph["analysis_limits"],
        },
        "allowed_evidence_paths": [item["path"] for item in observations],
        "allowed_repair_targets": [item["path"] for item in observations],
        "evidence_path_rule": (
            "Evidence uses 1-based inclusive line ranges from the numbered "
            "observations. Paths must exactly match allowed_evidence_paths. "
            "Do not cite the proposed patch as source evidence."
        ),
    }

    current_content = observed_files.get(path, "")
    context["proposed_diff"] = {
        "path": path,
        "before_write": current_content,
        "after_write": content,
        "change_kind": (
            "new_file"
            if not current_content
            else "no_op"
            if current_content == content
            else "modification"
        ),
        "evaluate_rule": (
            "Compare before_write with after_write. The successful_file_observations "
            "for this path reflect the PRE-WRITE state; do not evaluate that state, "
            "evaluate the delta. If after_write resolves the diagnosed defect, "
            "APPROVE, regardless of implementation style. Do not prescribe an algorithm."
        ),
    }

    return [
        {"role": "system", "content": CAUSAL_REVIEW_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(context, ensure_ascii=False),
        },
    ]



_IMPLEMENTATION_RECIPE_PATTERNS = (
    re.compile(r"```"),
    re.compile(
        r"\b(?:source|text|content|inner|chars?)\s*\[[^\]\n]+\]",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?m)^\s*(?:if|elif|else|for|while|def|return)\s+"
        r"[^;\n]{0,180}(?:==|!=|<=|>=|:=|:)\s*"
    ),
    re.compile(
        r"\b[A-Za-z_]\w*\s*(?:\+=|-=|:=|=(?!=))\s*"
        r"(?:not\b|True\b|False\b|['\"\d])"
    ),
    re.compile(
        r"\b(?:check|test)\s+(?:whether|if)\b"
        r".{0,120}\b(?:previous|preceding|prior)\s+"
        r"(?:character|char|index|backslash)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:previous|preceding|prior)\s+(?:character|char)\s+"
        r"(?:is|was)\s+(?:a\s+)?backslash\b",
        re.IGNORECASE,
    ),
)


def _contains_implementation_recipe(guidance: str) -> bool:
    """Detect recognizable code snippets and implementation prescriptions."""
    return any(
        pattern.search(guidance)
        for pattern in _IMPLEMENTATION_RECIPE_PATTERNS
    )


def parse_prewrite_review(
    response: str,
    observed_files: dict[str, str],
    proposed_path: str,
) -> dict[str, Any]:
    """Validate evidence line ranges against successfully observed source files."""
    if not isinstance(response, str):
        raise CausalReviewError("Review response must be a string.")

    text = response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or not lines[-1].strip().startswith("```"):
            raise CausalReviewError("Incomplete JSON code fence.")
        text = "\n".join(lines[1:-1]).strip()

    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CausalReviewError(
            f"Invalid review JSON: {exc}"
        ) from exc

    required = {
        "decision",
        "root_cause",
        "causal_chain",
        "evidence",
        "repair_target",
        "guidance",
    }

    if not isinstance(value, dict) or set(value) != required:
        raise CausalReviewError("Review has missing or unexpected fields.")

    decision = value["decision"]
    if decision not in {"APPROVE", "REVISE", "INVESTIGATE"}:
        raise CausalReviewError("Unknown review decision.")

    def check_text(field: str, maximum: int, allow_empty: bool = False) -> str:
        item = value[field]
        if not isinstance(item, str):
            raise CausalReviewError(f"{field} must be a string.")
        item = item.strip()
        if not item and not allow_empty:
            raise CausalReviewError(f"{field} must not be empty.")
        if len(item) > maximum:
            raise CausalReviewError(f"{field} exceeds {maximum} characters.")
        return item

    root_cause = check_text("root_cause", 600)
    repair_target = check_text("repair_target", 500, allow_empty=True)
    guidance = check_text("guidance", 1200)
    if _contains_implementation_recipe(guidance):
        raise CausalReviewError(
            "guidance must be diagnostic-only and must not prescribe "
            "an implementation."
        )

    causal_chain = value["causal_chain"]
    if (
        not isinstance(causal_chain, list)
        or not 1 <= len(causal_chain) <= 5
    ):
        raise CausalReviewError("causal_chain must contain 1 to 5 items.")

    normalized_chain = []
    for item in causal_chain:
        if not isinstance(item, str) or not item.strip() or len(item) > 400:
            raise CausalReviewError("Invalid causal_chain item.")
        normalized_chain.append(item.strip())

    evidence = value["evidence"]
    if not isinstance(evidence, list) or len(evidence) > 5:
        raise CausalReviewError("evidence must contain at most 5 items.")

    normalized_evidence = []
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {
            "path", "start_line", "end_line"
        }:
            raise CausalReviewError("Invalid evidence entry.")

        path = item["path"]
        start_line = item["start_line"]
        end_line = item["end_line"]

        if not isinstance(path, str) or not path.strip():
            raise CausalReviewError("Evidence path must not be empty.")

        if (
            not isinstance(start_line, int)
            or isinstance(start_line, bool)
            or not isinstance(end_line, int)
            or isinstance(end_line, bool)
            or start_line < 1
            or end_line < start_line
            or end_line - start_line + 1 > 20
        ):
            raise CausalReviewError("Invalid evidence line range.")

        source = observed_files.get(path)
        if not isinstance(source, str):
            raise CausalReviewError(
                f"Evidence path {path!r} was not observed."
            )

        source_lines = source.splitlines()
        if end_line > len(source_lines):
            raise CausalReviewError(
                f"Evidence line range is outside observed source {path!r}."
            )

        # NOVA, not the language model, extracts the actual source text.
        quote = "\\n".join(source_lines[start_line - 1:end_line])
        if not quote.strip():
            raise CausalReviewError("Evidence range contains no source text.")

        normalized_evidence.append({
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "quote": quote,
        })

    if decision == "APPROVE":
        if not normalized_evidence:
            raise CausalReviewError("APPROVE requires exact source evidence.")
        if repair_target != proposed_path:
            raise CausalReviewError(
                "APPROVE repair_target must match the proposed write path."
            )
        if proposed_path not in observed_files:
            raise CausalReviewError(
                "APPROVE requires the proposed target file to have been observed."
            )

    if decision == "REVISE" and not normalized_evidence:
        raise CausalReviewError("REVISE requires exact source evidence.")
    if decision == "REVISE" and repair_target not in observed_files:
        raise CausalReviewError(
            "REVISE repair_target must be an exactly observed file path."
        )

    if decision == "INVESTIGATE" and not guidance:
        raise CausalReviewError("INVESTIGATE requires investigation guidance.")

    return {
        "decision": decision,
        "root_cause": root_cause,
        "causal_chain": normalized_chain,
        "evidence": normalized_evidence,
        "repair_target": repair_target,
        "guidance": guidance,
    }


def discover_observed_dependencies(
    observed_files: dict[str, str],
) -> list[dict[str, Any]]:
    """Extract direct, observed local Python import and symbol-use edges.

    This reports syntax-level facts only. It does not claim that a dependency
    is defective or that an import necessarily causes the observed symptom.
    """
    if not isinstance(observed_files, dict):
        raise TypeError("observed_files must be a dictionary.")

    module_paths: dict[str, str] = {}
    parsed_sources: dict[str, ast.Module] = {}

    for path, source in observed_files.items():
        if not isinstance(path, str) or not isinstance(source, str):
            continue

        relative = PurePosixPath(path)
        if relative.suffix != ".py":
            continue

        if relative.name == "__init__.py":
            module_parts = relative.parts[:-1]
        else:
            module_parts = relative.parts[:-1] + (relative.stem,)

        module_name = ".".join(module_parts)
        if module_name:
            module_paths[module_name] = path

        try:
            parsed_sources[path] = ast.parse(source, filename=path)
        except SyntaxError:
            continue

    edges: list[dict[str, Any]] = []

    for importer_path, importer_tree in parsed_sources.items():
        importer_source = observed_files[importer_path]
        call_names = {
            node.func.id
            for node in ast.walk(importer_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
        }

        for node in ast.walk(importer_tree):
            module_name = None
            imported_names: list[str] = []
            aliases: dict[str, str] = {}

            if isinstance(node, ast.ImportFrom):
                # Relative imports need package-resolution semantics; omit
                # them rather than guessing an incorrect local target.
                if node.level != 0 or not node.module:
                    continue

                module_name = node.module
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    imported_names.append(alias.name)
                    aliases[alias.asname or alias.name] = alias.name

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name
                    imported_names = [alias.name]
                    aliases[alias.asname or alias.name.split(".")[0]] = alias.name

                    # One AST Import node may contain multiple imports.
                    dependency_path = module_paths.get(module_name)
                    if dependency_path is None:
                        continue

                    edges.append({
                        "importer_path": importer_path,
                        "dependency_path": dependency_path,
                        "module": module_name,
                        "imported_names": imported_names,
                        "used_imported_names": [],
                        "import_statement": ast.get_source_segment(
                            importer_source, node
                        ),
                        "dependency_definitions": [],
                    })
                continue

            if not module_name:
                continue

            dependency_path = module_paths.get(module_name)
            if dependency_path is None:
                continue

            used_names = sorted(
                original_name
                for local_name, original_name in aliases.items()
                if local_name in call_names
            )

            dependency_tree = parsed_sources.get(dependency_path)
            dependency_source = observed_files[dependency_path]
            definitions = []

            if dependency_tree is not None:
                wanted = set(imported_names)
                for definition in dependency_tree.body:
                    if (
                        isinstance(
                            definition,
                            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                        )
                        and definition.name in wanted
                    ):
                        snippet = ast.get_source_segment(
                            dependency_source, definition
                        )
                        if snippet:
                            definitions.append({
                                "name": definition.name,
                                "source": snippet[:2500],
                            })

            edges.append({
                "importer_path": importer_path,
                "dependency_path": dependency_path,
                "module": module_name,
                "imported_names": sorted(set(imported_names)),
                "used_imported_names": used_names,
                "import_statement": ast.get_source_segment(
                    importer_source, node
                ),
                "dependency_definitions": definitions,
            })

    # Stable output makes reviews and tests reproducible.
    unique = {}
    for edge in edges:
        key = (
            edge["importer_path"],
            edge["dependency_path"],
            edge["module"],
            tuple(edge["imported_names"]),
        )
        unique[key] = edge

    return [
        unique[key]
        for key in sorted(unique)
    ]
