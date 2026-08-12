# Load test results — POST /payments

Run against `docker compose up` on a laptop (not cloud infra) — see hardware note below.
Scenario: ramping VUs 0→20→50→100→0 over ~110s, `loadtest/k6/payments_load.js`.

## Connection pool tuning (before/after)

The first run used SQLAlchemy's default pool (`pool_size=5, max_overflow=10` — 15 max
connections), which became the bottleneck well before the application logic did under
100 concurrent VUs. Bumping to `pool_size=20, max_overflow=20` (`app/config.py`,
`db_pool_size`/`db_max_overflow`) and re-running against a fresh stack:

| Metric | Before (pool=15) | After (pool=40) |
|---|---|---|
| p95 latency | 1078.4 ms | **781.2 ms** (−28%) |
| Average latency | 304.8 ms | 289.4 ms |
| Sustained throughput | 136.5 req/s | **142.9 req/s** |
| Total requests | 15,118 | 15,837 |
| Error rate | 0.00% | 0.00% |

Zero errors in both runs — the remaining latency at peak load is queuing for a database
connection and the two extra round trips `POST /payments` deliberately takes for
idempotency safety (ADR-0002: claim-then-complete as two transactions, not one), not
failures. This is exactly the kind of number a laptop's Docker Desktop (shared CPU/IO
with everything else running on the machine) produces — it is not a cloud-scale
benchmark, and isn't presented as one.

**Hardware:** results generated locally via Docker Desktop; no dedicated/cloud
infrastructure was used. Re-running `k6 run loadtest/k6/payments_load.js` against
`docker compose up` on different hardware will produce different absolute numbers — the
before/after *shape* (pool size dominates at this connection count) is the reusable
finding.

## Idempotency proof

`python scripts/prove_idempotency.py --requests 20` fires N concurrent identical
`POST /payments` requests sharing one `Idempotency-Key` against the running stack and
reports how many payments actually got created. The same property is checked
automatically on every push by
`tests/integration/test_idempotency_api.py::test_n_concurrent_identical_requests_create_exactly_one_payment`
(parametrized over 3 repeated runs, to catch flakiness rather than passing once and
lying) — this script exists so the proof can also be run and read by hand.

```
Firing 20 concurrent identical POST /payments requests...

Completed in 0.15s
Status codes: {201: 15, 409: 5}
Distinct payment IDs created: 1 (expected: 1)
Payment ID: f7fa5818-2b18-4ff4-88f8-395e7c2e39fc

PASS: 20 concurrent retries with the same idempotency key produced exactly 1 payment.
```

20 concurrent retries, 1 payment. The 15/5 split between `201` and `409` responses is the
two-phase claim/complete design (ADR-0002) working as intended: whichever caller's
`INSERT ... ON CONFLICT` wins proceeds to create the payment (and later callers replay
its stored response once it completes), while callers that land while it's still
mid-flight get a fast `409` rather than blocking — never a second payment.
