# ADR-0005: Transactional outbox for webhook delivery

## Status
Accepted

## Context
A payment transition (settle, reverse, fail, ...) should notify subscribers via webhook.
The naive approach — commit the state change, then make the HTTP call — has an obvious
failure mode: if the process crashes (or the HTTP call itself hangs or fails) between the
commit and the notification, the state change is durable but the notification is lost
forever, with no record that one was ever owed.

## Decision
`enqueue_payment_webhook_event` (`app/domain/webhooks/services.py`) is never called with
its own transaction. It's called from *inside* the same already-open unit of work that
performs the payment's state transition (`app/domain/payments/services.py`), writing a
`webhook_deliveries` row in the same commit as the state change. The actual HTTP dispatch
happens later, out-of-band, driven by `app/domain/webhooks/dispatch.py` polling for
`status = 'pending'` rows and delivering them with HMAC-SHA256 request signing and
exponential backoff (`retry_policy.backoff_seconds`) up to a bounded attempt count, after
which a delivery moves to `dead_letter` (browsable via `GET /webhooks/dead-letters`).

This guarantees: a payment can never end up settled with no corresponding delivery
queued, and a delivery can never exist for a state change that didn't actually commit —
because they're the same transaction. It does *not* guarantee the HTTP call itself
succeeds or happens quickly; that's what the retry/backoff/DLQ machinery is for.

## Consequences
**Gains:** no lost notifications on crash, no notifications for state changes that got
rolled back, and dispatch latency is fully decoupled from the API request path — a slow
or unreachable subscriber endpoint never makes `POST /payments/{id}/settle` itself slow.

**Costs:** delivery is asynchronous by design — a subscriber is not guaranteed to be
notified within any particular time bound, only eventually (or moved to the DLQ after
exhausting retries). The worker (`app/workers/scheduler.py`) currently runs as a single
process polling every 5 seconds; if it were scaled to multiple replicas, two workers
could both pick up the same due delivery in the small window between listing and
dispatching (the list query has no row-level claim/lease). That's a real gap for
horizontal scaling, not one this project's single-worker docker-compose topology
actually needs — listed under "what's next" rather than silently assumed away.
