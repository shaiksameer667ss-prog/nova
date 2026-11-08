from client import make_client
from config import defaults


def test_uses_config_defaults():
    assert make_client() == {"timeout": 30, "retries": 3}


def test_applies_overrides():
    assert make_client(timeout=5) == {"timeout": 5, "retries": 3}


def test_does_not_mutate_defaults():
    before = defaults.copy()
    make_client(timeout=5)
    assert defaults == before