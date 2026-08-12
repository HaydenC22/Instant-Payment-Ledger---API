import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const ACCOUNT_PAIRS = 50; // created once in setup(), shared across all VUs

export const options = {
  scenarios: {
    ramping_payments: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "30s", target: 20 },
        { duration: "30s", target: 50 },
        { duration: "30s", target: 100 },
        { duration: "20s", target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_duration: ["p(95)<500"],
    http_req_failed: ["rate<0.01"],
  },
};

function jsonHeaders(extra) {
  return { headers: Object.assign({ "Content-Type": "application/json" }, extra || {}) };
}

// Runs once, before any VU starts — creates the debtor/creditor account pairs the
// payment-creation load draws from, so the load itself measures POST /payments, not
// account setup.
export function setup() {
  const pairs = [];
  const runId = Date.now();
  for (let i = 0; i < ACCOUNT_PAIRS; i++) {
    const suffix = `${runId}-${i}`;
    const debtor = http.post(
      `${BASE_URL}/accounts`,
      JSON.stringify({
        account_number: `LOAD-D-${suffix}`,
        owner_name: "Load Test Debtor",
        account_type: "customer",
        currency: "SGD",
      }),
      jsonHeaders(),
    );
    const creditor = http.post(
      `${BASE_URL}/accounts`,
      JSON.stringify({
        account_number: `LOAD-C-${suffix}`,
        owner_name: "Load Test Creditor",
        account_type: "customer",
        currency: "SGD",
      }),
      jsonHeaders(),
    );
    pairs.push({ debtor: debtor.json("id"), creditor: creditor.json("id") });
  }
  return { pairs };
}

export default function (data) {
  const pair = data.pairs[Math.floor(Math.random() * data.pairs.length)];
  // Unique per request, matching a real client generating one key per logical attempt —
  // this measures steady-state throughput, not the idempotency-replay path (that's
  // proven separately, see tests/integration/test_idempotency_api.py).
  const idempotencyKey = `${__VU}-${__ITER}-${Date.now()}-${Math.random()}`;

  const res = http.post(
    `${BASE_URL}/payments`,
    JSON.stringify({
      debtor_account_id: pair.debtor,
      creditor_account_id: pair.creditor,
      amount: "1.00",
      currency: "SGD",
    }),
    jsonHeaders({ "Idempotency-Key": idempotencyKey }),
  );

  check(res, { "payment created (201)": (r) => r.status === 201 });
}

export function handleSummary(data) {
  const p95 = data.metrics.http_req_duration.values["p(95)"];
  const avg = data.metrics.http_req_duration.values.avg;
  const reqRate = data.metrics.http_reqs.values.rate;
  const totalReqs = data.metrics.http_reqs.values.count;
  const failRate = data.metrics.http_req_failed ? data.metrics.http_req_failed.values.rate : 0;

  const summary =
    `# Load test results — POST /payments\n\n` +
    `Run at: ${new Date().toISOString()}\n\n` +
    `| Metric | Value |\n` +
    `|---|---|\n` +
    `| p95 latency | ${p95.toFixed(1)} ms |\n` +
    `| Average latency | ${avg.toFixed(1)} ms |\n` +
    `| Sustained throughput | ${reqRate.toFixed(1)} req/s |\n` +
    `| Total requests | ${totalReqs} |\n` +
    `| Error rate | ${(failRate * 100).toFixed(2)}% |\n\n` +
    `Thresholds: p95 < 500ms, error rate < 1%.\n`;

  return {
    "loadtest/results/summary.md": summary,
    stdout: summary,
  };
}
