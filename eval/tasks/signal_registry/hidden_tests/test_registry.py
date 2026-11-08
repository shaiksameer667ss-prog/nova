import pytest
from registry import broadcast

def test_broadcast_success():
    assert broadcast(["S1", "S2"]) == ["S1", "S2"]

def test_broadcast_empty():
    assert broadcast([]) == []