import pytest

from parser import parse_record


def test_plain_fields():
    assert parse_record("name=Ada; role=writer") == {
        "name": "Ada",
        "role": "writer",
    }


def test_semicolon_inside_quoted_value():
    assert parse_record('team="Research; Development"; owner=Sam') == {
        "team": "Research; Development",
        "owner": "Sam",
    }


def test_escaped_quote_and_semicolon_inside_quoted_value():
    source = r'label="A \"quoted; phrase\""; owner=Ops'
    assert parse_record(source) == {
        "label": 'A "quoted; phrase"',
        "owner": "Ops",
    }


def test_whitespace_rules():
    assert parse_record('  name = " Ada Lovelace " ; role = engineer  ') == {
        "name": " Ada Lovelace ",
        "role": "engineer",
    }


def test_empty_record():
    assert parse_record("   ") == {}


def test_unterminated_quoted_value_is_rejected():
    with pytest.raises(ValueError):
        parse_record('label="unfinished')