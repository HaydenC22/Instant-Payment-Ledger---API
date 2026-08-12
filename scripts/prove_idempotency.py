"""Standalone demo: fires N concurrent identical POST /payments requests sharing one
Idempotency-Key against a running stack, then reports how many payments actually got
created. Run with `docker compose up` already running:

    python scripts/prove_idempotency.py [--requests 20] [--base-url http://localhost:8000]

This is the same property tests/integration/test_idempotency_api.py checks automatically
on every push — this script exists so the proof can also be run and read by hand.
"""

import argparse
import asyncio
import time
import uuid
from collections import Counter

import httpx


async def _create_account(client: httpx.AsyncClient, account_number: str) -> str:
    response = await client.post(
        "/accounts",
        json={
            "account_number": account_number,
            "owner_name": "Idempotency Proof",
            "account_type": "customer",
            "currency": "SGD",
        },
    )
    response.raise_for_status()
    return response.json()["id"]


async def main(base_url: str, num_requests: int) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        suffix = str(uuid.uuid4())[:8]
        debtor_id = await _create_account(client, f"PROOF-D-{suffix}")
        creditor_id = await _create_account(client, f"PROOF-C-{suffix}")

        idempotency_key = str(uuid.uuid4())
        body = {
            "debtor_account_id": debtor_id,
            "creditor_account_id": creditor_id,
            "amount": "10.00",
            "currency": "SGD",
        }

        async def attempt() -> httpx.Response:
            return await client.post(
                "/payments", json=body, headers={"Idempotency-Key": idempotency_key}
            )

        print(f"Firing {num_requests} concurrent identical POST /payments requests...")
        started = time.perf_counter()
        responses = await asyncio.gather(*(attempt() for _ in range(num_requests)))
        elapsed = time.perf_counter() - started

        status_counts = Counter(r.status_code for r in responses)
        payment_ids = {r.json()["id"] for r in responses if r.status_code == 201}

        print(f"\nCompleted in {elapsed:.2f}s")
        print(f"Status codes: {dict(status_counts)}")
        print(f"Distinct payment IDs created: {len(payment_ids)} (expected: 1)")
        print(f"Payment ID: {next(iter(payment_ids)) if payment_ids else 'NONE'}")

        if len(payment_ids) == 1:
            print(
                f"\nPASS: {num_requests} concurrent retries with the same idempotency key "
                "produced exactly 1 payment."
            )
        else:
            print(
                f"\nFAIL: expected exactly 1 payment, got {len(payment_ids)}. "
                "This would mean idempotency is broken."
            )
            raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    asyncio.run(main(args.base_url, args.requests))
