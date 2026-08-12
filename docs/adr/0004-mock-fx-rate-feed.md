# ADR-0004: A seeded mock FX rate feed, not a live market connection

## Status
Accepted

## Context
Multi-currency settlement needs an exchange rate. A real bank connects to a live market
data feed (Bloomberg, Reuters, or an internal treasury system) with rates that move
continuously. This project is a portfolio piece that must run entirely offline via
`docker compose up` — no paid API keys, no external network dependency at test or demo
time — while still demonstrating the *mechanism* a live feed would plug into correctly.

## Decision
`fx_rates` is a plain table (`base_currency`, `quote_currency`, `rate`, `booked_at`,
`source`), seeded with a small fixed set of SGD/USD/EUR/GBP crosses directly in the M7
migration (`853dcecf0a07_fx_rates_and_fx_suspense_account.py`), tagged
`source='mock-feed'`. `FxRateRepository.get_latest_rate` always picks the most recent row
for a currency pair — the *lookup* mechanism (query by pair, order by recency, take the
latest) is exactly what a live-feed-backed implementation would also do; only the source
of the rows differs. Swapping in a real feed later means adding a poller that inserts new
`fx_rates` rows on a schedule — no change to `FxRateRepository`'s interface, or to
anything that calls it.

The rate actually used at settlement is booked onto the payment itself
(`payments.fx_rate_id`, `payments.creditor_amount` — see the settlement logic in
`app/domain/payments/services.py`), not recomputed later. This matters independently of
where rates come from: a reversal must undo the *exact* amount that was moved, not
re-price the trade against whatever the rate is at reversal time.

## Consequences
**Gains:** the project runs fully offline, with deterministic, reviewable exchange rates
(no flaky external dependency in CI or for a reviewer running the repo). The rate-booking
behaviour (store what was used, don't recompute on reversal) is exercised by a real test
that changes the seeded rate between settle and reverse and asserts the reversal still
uses the original amount — a property that would matter identically with a live feed.

**Costs:** the rates are static reference data, not real market prices — this is
explicitly not suitable for anything beyond demonstrating the mechanism, and the README
says so under its synthetic-data disclaimer. "What's next" lists a real feed integration
as the natural extension, requiring no interface changes on the consuming side.
