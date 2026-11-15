"""Static repository graph for observed Python source."""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any


def _module_name(path: str) -> str | None:
    if "\\" in path:
        return None
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    if relative.suffix != ".py":
        return None
    parts = (
        relative.parts[:-1]
        if relative.name == "__init__.py"
        else relative.parts[:-1] + (relative.stem,)
    )
    return ".".join(parts) or None


def _definitions(body, prefix=()):
    for node in body:
        if isinstance(node, ast.ClassDef):
            qualified = ".".join((*prefix, node.name))
            yield node, qualified, "class"
            yield from _definitions(node.body, (*prefix, node.name))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualified = ".".join((*prefix, node.name))
            kind = (
                "async_function"
                if isinstance(node, ast.AsyncFunctionDef)
                else "function"
            )
            yield node, qualified, kind
            yield from _definitions(node.body, (*prefix, node.name))


def _calls_in_scope(definition):
    """Collect calls owned by a function, excluding nested scopes."""
    pending = list(reversed(definition.body))
    while pending:
        node = pending.pop()
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
                ast.Lambda,
            ),
        ):
            continue
        if isinstance(node, ast.Call):
            yield node
        pending.extend(reversed(list(ast.iter_child_nodes(node))))


def build_repository_graph(
    observed_files: dict[str, str],
    *,
    imports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build deterministic file, definition, import and call-edge records.

    Only observed source is parsed. No repository code is imported or executed.
    Dynamic dispatch and ambiguous module names remain unresolved.
    """
    if not isinstance(observed_files, dict):
        raise TypeError("observed_files must be a dictionary.")
    if imports is not None and not isinstance(imports, list):
        raise TypeError("imports must be a list.")

    module_candidates = defaultdict(list)
    parsed = {}
    records = []

    for path, text in sorted(observed_files.items()):
        if not isinstance(path, str) or not isinstance(text, str):
            continue
        module = _module_name(path)
        if module is None:
            continue

        module_candidates[module].append(path)
        record = {
            "path": path,
            "module": module,
            "parse_status": "parsed",
            "parse_error": None,
            "definitions": [],
        }
        try:
            parsed[path] = ast.parse(text, filename=path)
        except (SyntaxError, ValueError) as exc:
            record["parse_status"] = "syntax_error"
            record["parse_error"] = (
                exc.msg if isinstance(exc, SyntaxError) else str(exc)
            )
        records.append(record)

    # Never guess when two observed files map to the same module name.
    modules = {
        name: paths[0]
        for name, paths in module_candidates.items()
        if len(paths) == 1
    }
    records_by_path = {item["path"]: item for item in records}
    definitions_by_path = {}
    call_edges = []

    for path, tree in sorted(parsed.items()):
        found = list(_definitions(tree.body))
        names = {qualified for _, qualified, _ in found}
        names.update(
            node.name
            for node in tree.body
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            )
        )
        definitions_by_path[path] = names

        for node, qualified, kind in found:
            records_by_path[path]["definitions"].append({
                "name": node.name,
                "qualified_name": qualified,
                "kind": kind,
                "start_line": node.lineno,
                "end_line": node.end_lineno,
            })

    for path, tree in sorted(parsed.items()):
        imported_symbols = {}
        imported_modules = {}

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level != 0 or not node.module:
                    continue
                dependency = modules.get(node.module)
                if dependency is None:
                    continue
                for alias in node.names:
                    if alias.name != "*":
                        imported_symbols[alias.asname or alias.name] = (
                            dependency,
                            alias.name,
                        )

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    dependency = modules.get(alias.name)
                    if dependency is None:
                        continue
                    local = alias.asname or alias.name.split(".")[0]
                    if "." not in alias.name or alias.asname:
                        imported_modules[local] = dependency

        for definition, qualified, kind in _definitions(tree.body):
            if kind == "class":
                continue

            for call in _calls_in_scope(definition):
                target_path = None
                target_symbol = None
                resolution = "unresolved"
                target = call.func

                if isinstance(target, ast.Name):
                    class_prefix = qualified.rpartition(".")[0]
                    class_candidate = (
                        f"{class_prefix}.{target.id}" if class_prefix else ""
                    )

                    if class_candidate in definitions_by_path[path]:
                        target_path = path
                        target_symbol = class_candidate
                        resolution = "same_class"
                    elif target.id in definitions_by_path[path]:
                        target_path = path
                        target_symbol = target.id
                        resolution = "same_module"
                    elif target.id in imported_symbols:
                        candidate_path, candidate_symbol = (
                            imported_symbols[target.id]
                        )
                        if candidate_symbol in definitions_by_path.get(
                            candidate_path, set()
                        ):
                            target_path = candidate_path
                            target_symbol = candidate_symbol
                            resolution = "imported_symbol"

                elif (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                ):
                    base = target.value.id

                    if base in imported_modules:
                        candidate_path = imported_modules[base]
                        if target.attr in definitions_by_path.get(
                            candidate_path, set()
                        ):
                            target_path = candidate_path
                            target_symbol = target.attr
                            resolution = "imported_module_attribute"

                    elif base in {"self", "cls"}:
                        class_prefix = qualified.rpartition(".")[0]
                        candidate = f"{class_prefix}.{target.attr}"
                        if candidate in definitions_by_path[path]:
                            target_path = path
                            target_symbol = candidate
                            resolution = "same_class"

                    elif base in imported_symbols:
                        candidate_path, candidate_symbol = (
                            imported_symbols[base]
                        )
                        candidate = f"{candidate_symbol}.{target.attr}"
                        if candidate in definitions_by_path.get(
                            candidate_path, set()
                        ):
                            target_path = candidate_path
                            target_symbol = candidate
                            resolution = "imported_class_attribute"

                expression = ast.get_source_segment(
                    observed_files[path], target
                ) or type(target).__name__

                call_edges.append({
                    "source_path": path,
                    "source_symbol": qualified,
                    "target_path": target_path,
                    "target_symbol": target_symbol,
                    "call_expression": expression,
                    "line": call.lineno,
                    "resolution": resolution,
                })

    for record in records:
        record["definitions"].sort(
            key=lambda item: (
                item["start_line"],
                item["qualified_name"],
                item["kind"],
            )
        )

    call_edges.sort(
        key=lambda item: (
            item["source_path"],
            item["line"],
            item["source_symbol"],
            item["call_expression"],
        )
    )

    return {
        "schema_version": 1,
        "files": records,
        "imports": imports if imports is not None else [],
        "calls": call_edges,
        "analysis_limits": [
            "Static source analysis only; no repository code was executed.",
            "Dynamic dispatch and ambiguous imports remain unresolved.",
            "Call edges are structural evidence, not proof of causality.",
        ],
    }
