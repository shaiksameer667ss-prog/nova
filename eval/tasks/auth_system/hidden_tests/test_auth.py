
from auth import provision_users


def test_provision_success():
    assert provision_users(["alice", "bob"]) == ["alice", "bob"]


def test_provision_empty():
    assert provision_users([]) == []
