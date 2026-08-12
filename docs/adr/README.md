# Architecture Decision Records

Short records of the decisions in this project that a reviewer can't infer from the code
alone — the trade-off each one accepted and why.

| ADR | Decision |
|---|---|
| [0001](0001-derived-balances.md) | Derived balances over a mutable `balance` column |
| [0002](0002-idempotency-key-storage.md) | Idempotency key storage & the two-phase claim/complete split |
| [0003](0003-optimistic-locking.md) | Optimistic locking via an account-level version token |
| [0004](0004-mock-fx-rate-feed.md) | A seeded mock FX rate feed, not a live market connection |
| [0005](0005-transactional-outbox-for-webhooks.md) | Transactional outbox for webhook delivery |
