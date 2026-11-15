import pytest

from nova.intelligence.repository_graph import build_repository_graph


def _edge(graph, caller, expression):
    matches = [
        edge for edge in graph["calls"]
        if edge["source_symbol"] == caller
        and edge["call_expression"] == expression
    ]
    assert len(matches) == 1
    return matches[0]


def test_imported_function_call_resolves_across_files():
    graph = build_repository_graph({
        "parser.py": (
            "from tokenizer import split_fields\n"
            "def parse_record(source):\n"
            "    return split_fields(source)\n"
        ),
        "tokenizer.py": (
            "def split_fields(source):\n"
            "    return source.split(';')\n"
        ),
    })
    edge = _edge(graph, "parse_record", "split_fields")
    assert edge["target_path"] == "tokenizer.py"
    assert edge["target_symbol"] == "split_fields"
    assert edge["resolution"] == "imported_symbol"


def test_aliased_import_resolves():
    graph = build_repository_graph({
        "parser.py": (
            "from tokenizer import split_fields as split\n"
            "def parse_record(source):\n"
            "    return split(source)\n"
        ),
        "tokenizer.py": "def split_fields(source):\n    return [source]\n",
    })
    edge = _edge(graph, "parse_record", "split")
    assert edge["target_path"] == "tokenizer.py"
    assert edge["target_symbol"] == "split_fields"


def test_module_attribute_call_resolves():
    graph = build_repository_graph({
        "parser.py": (
            "import tokenizer as tok\n"
            "def parse_record(source):\n"
            "    return tok.split_fields(source)\n"
        ),
        "tokenizer.py": "def split_fields(source):\n    return [source]\n",
    })
    edge = _edge(graph, "parse_record", "tok.split_fields")
    assert edge["target_path"] == "tokenizer.py"
    assert edge["resolution"] == "imported_module_attribute"


def test_same_module_call_resolves():
    graph = build_repository_graph({
        "parser.py": (
            "def normalize(value):\n"
            "    return value.strip()\n"
            "def parse_record(source):\n"
            "    return normalize(source)\n"
        ),
    })
    edge = _edge(graph, "parse_record", "normalize")
    assert edge["target_path"] == "parser.py"
    assert edge["resolution"] == "same_module"


def test_dynamic_call_remains_unresolved():
    graph = build_repository_graph({
        "parser.py": (
            "def parse_record(source, handler):\n"
            "    return handler(source)\n"
        ),
    })
    edge = _edge(graph, "parse_record", "handler")
    assert edge["target_path"] is None
    assert edge["resolution"] == "unresolved"


def test_class_method_call_resolves():
    graph = build_repository_graph({
        "service.py": (
            "class Parser:\n"
            "    def normalize(self, value):\n"
            "        return value.strip()\n"
            "    def parse(self, value):\n"
            "        return self.normalize(value)\n"
        ),
    })
    edge = _edge(graph, "Parser.parse", "self.normalize")
    assert edge["target_path"] == "service.py"
    assert edge["target_symbol"] == "Parser.normalize"


def test_syntax_error_does_not_abort_other_files():
    graph = build_repository_graph({
        "broken.py": "def broken(:\n    pass\n",
        "valid.py": "def parse_record(value):\n    return value\n",
    })
    broken = next(x for x in graph["files"] if x["path"] == "broken.py")
    valid = next(x for x in graph["files"] if x["path"] == "valid.py")
    assert broken["parse_status"] == "syntax_error"
    assert valid["parse_status"] == "parsed"


def test_graph_is_deterministic():
    files = {
        "parser.py": (
            "from tokenizer import split_fields\n"
            "def parse_record(source):\n"
            "    return split_fields(source)\n"
        ),
        "tokenizer.py": "def split_fields(source):\n    return [source]\n",
    }
    assert build_repository_graph(files) == build_repository_graph(
        dict(reversed(list(files.items())))
    )


def test_graph_rejects_non_dictionary_input():
    with pytest.raises(TypeError, match="dictionary"):
        build_repository_graph([])
