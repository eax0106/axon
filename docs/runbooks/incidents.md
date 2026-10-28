# Incidents

Start with `GET /admin/alerts` and `GET /admin/system` (staff token). Alerts name unhealthy vendors, low vendor balances, number purchases waiting to be settled and a silent worker.

| Symptom | Check | Do |
|---|---|---|
| `/readyz` answers 503 | The body names `postgres` or `redis` | Restore the dependency. The API recovers by itself; sign-in and sign-up keep answering without Redis (their limits pause) |
| Alert `worker_silent`, no dials, no analysis, no webhooks | `/admin/system` shows the worker's last heartbeat; the container's logs | Restart `worker`. Waiting work is in Postgres and Redis and resumes. Nothing is lost, calls are late |
| Calls do not start; Instant calls wait; campaigns say they are waiting | `/admin/provider-health` (a vendor scored unhealthy: at least 3 failures that are half or more of the last 10 minutes), `/admin/capacity` (calls in flight against `AXON_MAX_CONCURRENT_CALLS`) | A vendor down: nothing to do but wait and tell the vendor, the platform retries and falls back by itself; fix a missing or rejected key. At the cap: raise it only if [capacity.md](capacity.md) says the engines can carry more |
| One vendor failing mid-call | `failover` events on the call; `/admin/provider-health` | None needed: the call moved to the next vendor. A Premium call that fell back is billed at the cheaper tier |
| Vendor balance low | `/admin/provider-balances`; staff type the balance in with `PUT /admin/provider-balances/{vendor}` after topping up | Top up at the vendor, then record it |
| A number purchase stuck in `reconcile` | `/admin/capacity` lists them | Check the carrier's console. If Vobiz holds the number, `POST /admin/numbers/{number_id}/settle` with `kept`; if not, `refunded` (once; refused if the charge cannot be found) |
| A user is locked out (HTTP 429 on sign-in) | The `Retry-After` header says when it ends (15 minutes after the first try) | Wait, or clear it: `redis-cli DEL rl:login:email:<email-in-lowercase>`; for an address, `rl:login:address:<ip>`; for sign-ups, `rl:signup:<ip>` |
| Everyone is locked out of sign-in | All requests come from one address: `FORWARDED_ALLOW_IPS` is missing ([deploy.md](deploy.md)) | Set it to the proxy's address and restart `api`; clear `rl:login:address:*` |
| A call has no summary or fields | The call's `analysis_status` | `POST /calls/{call_id}/reanalyze`. A failed analysis is retried after 2 and then 10 minutes by itself |
| A customer's webhook receiver was down | `/developer/deliveries` | `POST /developer/deliveries/{delivery_id}/resend` once their receiver is back |
| Disk full on Postgres | `df`, `pg_database_size` | The largest tables are `call_events`, `calls` (transcripts) and `provider_outcomes` (pruned hourly to 7 days). Grow the disk; do not delete rows by hand without a backup |
| Redis lost its data | Nothing to restore | Restart it. Live-call views drop; waiting dials are re-queued by the worker from the database; rate limit counters reset |
| Data lost or corrupted | | [backup-restore.md](backup-restore.md) |

**A customer reports a wrong charge:** `POST /admin/accounts/{account_id}/credits` posts an adjustment to the ledger (it can never take the balance below zero) and writes an audit row. Do not edit the ledger directly.

**Support session:** to see what a customer sees, `POST /admin/accounts/{account_id}/impersonate` with a written reason; it lasts 30 minutes, every change made in it is in the audit log under your id, and it cannot reach `/admin`, change the password or set up anything that outlives the session.
