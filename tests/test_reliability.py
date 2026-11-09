import pytest

from nova.controller.reliability import (
    FailureTracker,
    create_failure_fingerprint,
    normalize_error_message,
)


def test_same_failure_has_same_fingerprint():
    first = create_failure_fingerprint(
        "read_file", "FileNotFoundError", "not found: ledger.py"
    )
    second = create_failure_fingerprint(
        "read_file", "FileNotFoundError", "not found: ledger.py"
    )
    assert first == second


def test_same_failure_has_same_fingerprint_across_actions():
    first = create_failure_fingerprint(
        "read_file", "ValueError", "invalid path"
    )
    second = create_failure_fingerprint(
        "write_file", "ValueError", "invalid path"
    )
    assert first == second


def test_different_exception_types_have_different_fingerprints():
    first = create_failure_fingerprint(
        "read_file", "FileNotFoundError", "missing"
    )
    second = create_failure_fingerprint(
        "read_file", "PermissionError", "missing"
    )
    assert first != second


def test_windows_paths_are_normalized():
    first = normalize_error_message(
        r"Access denied: C:\Users\Alice\workspace\file.py"
    )
    second = normalize_error_message(
        r"Access denied: D:\Agents\Bob\workspace\file.py"
    )
    assert first == second
    assert "<path>" in first


def test_uuids_are_normalized():
    first = normalize_error_message(
        "operation failed for 12345678-1234-1234-1234-123456789abc"
    )
    second = normalize_error_message(
        "operation failed for abcdefab-cdef-abcd-efab-cdefabcdefab"
    )
    assert first == second


def test_memory_addresses_are_normalized():
    first = normalize_error_message("object at 0xABCDEF")
    second = normalize_error_message("object at 0x123456")
    assert first == second


def test_whitespace_and_case_are_normalized():
    first = normalize_error_message("  File   NOT Found  ")
    second = normalize_error_message("file not found")
    assert first == second


def test_non_string_message_is_rejected():
    with pytest.raises(TypeError):
        normalize_error_message(123)


def test_fingerprint_is_sha256():
    fingerprint = create_failure_fingerprint(
        "read_file", "FileNotFoundError", "missing"
    )
    assert len(fingerprint) == 64
    int(fingerprint, 16)


def test_tracker_counts_repeated_failures():
    tracker = FailureTracker(threshold=3)

    first = tracker.record_failure(
        "read_file", "FileNotFoundError", "missing: ledger.py"
    )
    second = tracker.record_failure(
        "read_file", "FileNotFoundError", "missing: ledger.py"
    )
    third = tracker.record_failure(
        "read_file", "FileNotFoundError", "missing: ledger.py"
    )

    assert first.occurrence_count == 1
    assert second.occurrence_count == 2
    assert third.occurrence_count == 3
    assert first.should_stop is False
    assert second.should_stop is False
    assert third.should_stop is True


def test_tracker_keeps_different_failures_separate():
    tracker = FailureTracker(threshold=2)

    first = tracker.record_failure(
        "read_file", "FileNotFoundError", "missing"
    )
    second = tracker.record_failure(
        "read_file", "PermissionError", "missing"
    )

    assert first.fingerprint != second.fingerprint
    assert first.occurrence_count == 1
    assert second.occurrence_count == 1
    assert second.should_stop is False


def test_successful_actions_do_not_mutate_failure_count():
    tracker = FailureTracker(threshold=3)

    first = tracker.record_failure(
        "list_files", "ValueError", "path error"
    )

    # Other successful actions do not call record_failure.
    second = tracker.record_failure(
        "list_files", "ValueError", "path error"
    )

    assert first.fingerprint == second.fingerprint
    assert second.occurrence_count == 2


@pytest.mark.parametrize("threshold", [0, -1, True, 1.5])
def test_invalid_threshold_is_rejected(threshold):
    with pytest.raises(ValueError):
        FailureTracker(threshold=threshold)

def test_success_resets_failure_history_for_same_action():
    tracker = FailureTracker(threshold=3)

    first = tracker.record_failure(
        "list_files", "ValueError", "path error"
    )
    assert first.occurrence_count == 1

    tracker.record_success("list_files")

    after_recovery = tracker.record_failure(
        "list_files", "ValueError", "path error"
    )
    assert after_recovery.occurrence_count == 1
    assert after_recovery.should_stop is False


def test_success_of_another_action_does_not_reset_failure_history():
    tracker = FailureTracker(threshold=3)

    tracker.record_failure("list_files", "ValueError", "path error")
    tracker.record_success("read_file")

    second = tracker.record_failure(
        "list_files", "ValueError", "path error"
    )
    assert second.occurrence_count == 2


def test_success_resets_all_fingerprints_for_that_action():
    tracker = FailureTracker(threshold=3)

    tracker.record_failure("read_file", "FileNotFoundError", "missing")
    tracker.record_failure("read_file", "PermissionError", "denied")

    tracker.record_success("read_file")

    first = tracker.record_failure(
        "read_file", "FileNotFoundError", "missing"
    )
    second = tracker.record_failure(
        "read_file", "PermissionError", "denied"
    )

    assert first.occurrence_count == 1
    assert second.occurrence_count == 1



def test_tracker_combines_same_failure_across_different_actions():
    tracker = FailureTracker(threshold=3)

    first = tracker.record_failure(
        "read_file", "PermissionError", "access denied"
    )
    second = tracker.record_failure(
        "write_file", "PermissionError", "access denied"
    )
    third = tracker.record_failure(
        "list_files", "PermissionError", "access denied"
    )

    assert first.fingerprint == second.fingerprint == third.fingerprint
    assert first.occurrence_count == 1
    assert second.occurrence_count == 2
    assert third.occurrence_count == 3
    assert third.should_stop is True


def test_success_resets_only_that_tool_contribution():
    tracker = FailureTracker(threshold=3)

    tracker.record_failure("read_file", "PermissionError", "denied")
    tracker.record_failure("write_file", "PermissionError", "denied")

    tracker.record_success("read_file")

    decision = tracker.record_failure(
        "list_files", "PermissionError", "denied"
    )

    assert decision.occurrence_count == 2
    assert decision.should_stop is False
