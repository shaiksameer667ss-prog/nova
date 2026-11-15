from nova.controller.loop import _validate_python_source


def test_valid_python_is_accepted():
    assert _validate_python_source("parser.py", "def parse():\n    return {}") is None


def test_invalid_python_returns_location():
    error = _validate_python_source("tokenizer.py", "def split_fields(:\n")
    assert error is not None
    assert "tokenizer.py: line 1" in error


def test_non_python_files_are_skipped():
    assert _validate_python_source("notes.txt", "not python :::") is None


def test_utf8_bom_does_not_break_validation():
    assert _validate_python_source("module.py", "\ufeffdef parse():\n    return {}") is None
