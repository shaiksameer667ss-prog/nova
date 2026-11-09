import hashlib
import json
import re
from dataclasses import dataclass

UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}\b"
)
WINDOWS_PATH_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:\\|\\\\)[^\s\"']+"
)
UNIX_PATH_PATTERN = re.compile(
    r"(?<![\w])/(?:[^/\s]+/)*[^/\s]+"
)
MEMORY_ADDRESS_PATTERN = re.compile(r"\b0x[0-9a-fA-F]+\b")
WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_error_message(message: str) -> str:
    """Normalize unstable environment-specific details in error messages."""
    if not isinstance(message, str):
        raise TypeError("Error message must be a string.")

    normalized = UUID_PATTERN.sub("<uuid>", message)
    normalized = WINDOWS_PATH_PATTERN.sub("<path>", normalized)
    normalized = UNIX_PATH_PATTERN.sub("<path>", normalized)
    normalized = MEMORY_ADDRESS_PATTERN.sub("<address>", normalized)
    normalized = WHITESPACE_PATTERN.sub(" ", normalized)

    return normalized.strip().lower()


def create_failure_fingerprint(
    action_name: str,
    error_type: str,
    error_message: str,
) -> str:
    """Create a deterministic SHA-256 fingerprint for a tool failure."""
    if not isinstance(action_name, str) or not action_name.strip():
        raise ValueError("action_name must not be empty.")

    if not isinstance(error_type, str) or not error_type.strip():
        raise ValueError("error_type must not be empty.")

    normalized_message = normalize_error_message(error_message)

    canonical = json.dumps(
        {
            "error_type": error_type,
            "message": normalized_message,
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FailureDecision:
    fingerprint: str
    occurrence_count: int
    threshold: int
    should_stop: bool


class FailureTracker:
    """Track repeated identical tool failures during one agent run."""

    def __init__(self, threshold: int = 3) -> None:
        if (
            not isinstance(threshold, int)
            or isinstance(threshold, bool)
            or threshold < 1
        ):
            raise ValueError("threshold must be a positive integer.")

        self.threshold = threshold
        self._counts: dict[tuple[str, str], int] = {}

    def record_failure(
        self,
        action_name: str,
        error_type: str,
        error_message: str,
    ) -> FailureDecision:
        fingerprint = create_failure_fingerprint(
            action_name,
            error_type,
            error_message,
        )

        key = (fingerprint, action_name)
        self._counts[key] = self._counts.get(key, 0) + 1
        count = sum(
            value
            for (known_fingerprint, _), value in self._counts.items()
            if known_fingerprint == fingerprint
        )

        return FailureDecision(
            fingerprint=fingerprint,
            occurrence_count=count,
            threshold=self.threshold,
            should_stop=count >= self.threshold,
        )

    def record_success(self, action_name: str) -> None:
        """Reset failure history for an action after a successful execution."""
        if not isinstance(action_name, str) or not action_name.strip():
            raise ValueError("action_name must not be empty.")

        resolved = [
            key for key in self._counts
            if key[1] == action_name
        ]
        for key in resolved:
            self._counts.pop(key, None)

    def count_for(self, fingerprint: str) -> int:
        return sum(
            value
            for (known_fingerprint, _), value in self._counts.items()
            if known_fingerprint == fingerprint
        )
