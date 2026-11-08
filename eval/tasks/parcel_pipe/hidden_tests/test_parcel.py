import pytest
from parcel import process_batch

def test_process_batch_success():
    assert process_batch(["A1", "A2"]) == ["A1", "A2"]

def test_process_batch_empty():
    assert process_batch([]) == []