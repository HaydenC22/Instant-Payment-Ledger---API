# ADR-0002: Idempotency key storage & the two-phase claim/complete split

## Status
Accepted

## Context
`POST /payments` creates a brand-new resource. A client that times out waiting for a
response has no way to know whether the payment was actually created — retrying naively
can create two payments that each later settle for real money. This is the specific
failure this project's interview hook is about: *"walk me through what happens when the
client's request times out after you've already written to the ledger."*

The other lifecycle transitions (`authorise`, `settle`, `reverse`, `fail`) don't have this
problem the same way: replaying an already-applied transition just hits the state machine
and 409s, rather than reapplying. So idempotency-key protection is scoped specifically to
payment initiation, not bolted onto every endpoint uniformly.

## Decision
A dedicated `idempotency_keys` table, unique on `(endpoint, key)`, storing the request's
SHA-256 hash and (once complete) the full response body and status code. The guarded
operation runs as **two transactions**, deliberately, not one:

1. **Claim** — `INSERT ... ON CONFLICT (endpoint, key) DO NOTHING`, committed immediately.
   Postgres blocks a second concurrent insert on the same key until the first transaction
   resolves, so by the time a conflicting caller's insert returns empty, the winner's
   claim is already durably committed — a concurrent duplicate can *see* `in_progress` and
   get a fast `409` instead of blocking for the full duration of the guarded operation.
2. **Complete** — the payment is created and the claim is marked `completed` together, in
   one transaction. A crash between "payment created" and "response recorded" is
   impossible: either both land in that commit, or neither does.

On replay (same key, same request hash, status `completed`), the *stored* response is
returned verbatim — not a freshly rebuilt one — so retries are byte-for-byte consistent
even if server-side formatting changes between the original attempt and the retry.

Currency validation is checked *before* phase 1 claims the key, not after — a currency
mismatch fails identically on every retry, so claiming the key first would orphan it
`in_progress` forever, and every subsequent retry would see a `409` instead of the real
`422`. This was caught by a test, not designed in up front: see the commit history on
`app/domain/payments/services.py` for the fix.

## Consequences
**Gains:** genuinely concurrent duplicate submissions get a fast, correct answer instead
of one blocking behind Postgres's row lock; a crash mid-request can never leave "payment
exists but caller doesn't know it" or "caller thinks it worked but nothing was created."

**Costs:** if the process crashes *between* phase 1's commit and phase 2's commit, that
key is left `in_progress` forever — no expiry/lease mechanism is implemented. In this
window the client's retries all see `409 Conflict` rather than eventually succeeding or
replaying. A production system would add a TTL sweep (e.g., a background job that marks
`in_progress` claims older than N minutes as failed, freeing the key for retry). Given
this window is only reachable by a process crash at a very specific instant — not by any
normal failure mode — it's an accepted, documented gap for this project's scope rather
than a silent one.
