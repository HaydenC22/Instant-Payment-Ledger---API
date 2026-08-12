import random

DEFAULT_MAX_ATTEMPTS = 5
_BASE_BACKOFF_SECONDS = 0.01
_MAX_BACKOFF_SECONDS = 0.2


def retry_backoff_seconds(attempt: int) -> float:
    """Full-jitter exponential backoff for optimistic-lock retries. attempt is 0-indexed."""
    ceiling = min(_MAX_BACKOFF_SECONDS, _BASE_BACKOFF_SECONDS * (2**attempt))
    return random.uniform(0, ceiling)  # noqa: S311 - retry jitter, not security-sensitive
