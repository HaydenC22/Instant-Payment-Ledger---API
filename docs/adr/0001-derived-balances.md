# ADR-0001: Derived balances over a mutable `balance` column

## Status
Accepted

## Context
The single most common shortcut in a student payments project is a `balance` column on
the account row, updated in place (`UPDATE accounts SET balance = balance + :amount`) on
every transfer. It's simple, but it throws away the one property that makes a ledger a
ledger rather than a counter: an auditable history of *why* the balance is what it is. A
mutated `balance` column can't be reconciled against history, can't prove it wasn't
double-updated, and can't be reconstructed at a past point in time.

## Decision
`accounts` has no `balance` column at all. Every movement of money writes immutable rows
to `journal_lines` (append-only, never updated or deleted), each tagged with a `direction`
(`debit`/`credit`), an `amount`, and a `currency`. A balance is always computed:

```sql
SELECT account_id, currency, SUM(CASE WHEN direction = 'credit' THEN amount ELSE -amount END) AS balance
FROM journal_lines
GROUP BY account_id, currency
```

This is exposed both as a reporting view (`account_balances`, for ad-hoc inspection) and
as the same aggregate query used directly by `LedgerRepository.get_balance` — the API
never has two different ideas of what a balance is.

Every journal entry is validated (`app/domain/ledger/invariants.py`) to net to exactly
zero *per currency* before it's allowed to post — this is the ledger's core correctness
invariant, and it's what the M1 integration tests exercise most heavily, including
concurrent postings under real Postgres.

## Consequences
**Gains:** full auditability (every balance is reconstructible at any point in time by
replaying journal lines up to a timestamp); trivial reconciliation (M6 matches settled
payments against an external file using exactly this same derived-balance discipline);
no possibility of a balance silently drifting from its supporting entries, because there
is no separate balance to drift.

**Costs:** every balance read is an aggregation over `journal_lines`, not an indexed point
lookup. At the row counts this project runs at (thousands, not billions), the index on
`journal_lines(account_id)` keeps this fast — the load test in `loadtest/results/`
confirms it. A production system with very high transaction volume per account would
likely add a periodically-refreshed balance *snapshot* (materialized view or a cached
column, explicitly labelled as a cache, rebuilt from the same aggregate) rather than
abandoning derived balances as the source of truth. That's out of scope here.
