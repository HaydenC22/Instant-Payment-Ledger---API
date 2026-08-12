from app.domain.webhooks.retry_policy import backoff_seconds


def test_backoff_increases_monotonically() -> None:
    delays = [backoff_seconds(attempt) for attempt in range(6)]
    assert delays == sorted(delays)
    assert len(set(delays[:5])) == 5  # strictly increasing before hitting the cap


def test_backoff_is_capped() -> None:
    assert backoff_seconds(100, base_seconds=2.0, max_seconds=900.0) == 900.0


def test_backoff_first_attempt_equals_base() -> None:
    assert backoff_seconds(0, base_seconds=3.0, max_seconds=900.0) == 3.0


def test_backoff_doubles_each_attempt_until_capped() -> None:
    assert backoff_seconds(1, base_seconds=2.0, max_seconds=900.0) == 4.0
    assert backoff_seconds(2, base_seconds=2.0, max_seconds=900.0) == 8.0
