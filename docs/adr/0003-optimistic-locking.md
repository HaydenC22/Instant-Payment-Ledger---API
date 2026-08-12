# ADR-0003: Optimistic locking via an account-level version token

## Status
Accepted

## Context
Because balances are derived (ADR-0001), there's no `balance` row to lock the way a naive
implementation would. Concurrent postings to the same account still need to be
serialized somehow — two simultaneous transfers debiting the same account must not both
proceed as if the other didn't exist, and neither should silently overwrite the other's
effect.

## Decision
`accounts.version` is a pure optimistic-lock token — an integer, unrelated to balance —
bumped on every posting that touches the account. `post_journal_entry`
(`app/domain/ledger/services.py`) reads each involved account's current version, inserts
the journal entry, then attempts:

```sql
UPDATE accounts SET version = version + 1 WHERE id = :id AND version = :expected_version
```

If any account's update affects zero rows, another transaction won the race since the
version was read — the whole attempt (including the journal entry insert) rolls back and
retries with fresh versions and full-jitter exponential backoff
(`retry_backoff_seconds`), up to a bounded attempt count, after which it surfaces as a
`409 ConcurrentModificationError` (ledger-level) or `ConcurrentPaymentModificationError`
(payment-level).

This is not a lock in the pessimistic sense — nothing blocks. Two conflicting
transactions can both proceed to the point of attempting their version bump; exactly one
succeeds, the other retries.

## Consequences
**Gains:** no long-held row locks, no deadlock risk between concurrent transfers, good
throughput under low-to-moderate contention (the common case — most accounts aren't
being written to by many transactions in the same instant). `tests/integration/test_ledger.py`
and `test_payments.py` prove this holds under real concurrent load against Postgres,
firing N simultaneous postings at a shared account and asserting the final balance is
exactly right regardless of interleaving — not just that it "usually" is.

**Costs:** under sustained high contention on a single hot account (many transactions
racing the same account simultaneously, continuously), retries pile up and the bounded
attempt count can be exhausted, surfacing as a `409` to the caller rather than eventually
succeeding. A pessimistic `SELECT ... FOR UPDATE` fallback path for known-hot accounts
(e.g., a settlement suspense account under heavy load) would trade some throughput for
guaranteed eventual success — not implemented here, and listed under "what's next" in the
README.
