DEFAULT_BASE_SECONDS = 2.0
DEFAULT_MAX_SECONDS = 900.0


def backoff_seconds(
    attempt: int,
    *,
    base_seconds: float = DEFAULT_BASE_SECONDS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
) -> float:
    """Exponential backoff with a cap. attempt is 0-indexed (0 = delay before the 2nd try)."""
    return min(max_seconds, base_seconds * (2**attempt))
