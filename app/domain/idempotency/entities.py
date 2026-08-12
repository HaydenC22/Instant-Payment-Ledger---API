from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class IdempotencyOutcomeKind(StrEnum):
    STARTED = "started"  # no prior record — caller now owns this attempt and should proceed
    REPLAY = "replay"  # a completed record with a matching request hash already exists
    IN_PROGRESS_CONFLICT = "in_progress_conflict"  # a concurrent attempt is still in flight
    HASH_MISMATCH = "hash_mismatch"  # the key was reused with a different request body


@dataclass(frozen=True, slots=True)
class IdempotencyOutcome:
    kind: IdempotencyOutcomeKind
    response_status_code: int | None = None
    response_body: dict[str, Any] | None = None
