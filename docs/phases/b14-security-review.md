# B14 security review

Scope: the whole Track 1 backend (API, engine, worker, deploy files) as of B14, by reading the code and by tests that sweep it. This is not the Strix penetration test, which runs once after B14 (phase SEC) against the running stack. Findings are numbered; each ends `fixed`, `accepted` (with the reason) or `owner` (needs the owner's decision).

## Findings

| # | Finding | Where | Outcome |
|---|---|---|---|
| F1 | Sign-in, sign-up and password change had no attempt limit, so passwords could be guessed and accounts mass-created (carried from B1) | `app/auth.py`, `app/ratelimit.py` | fixed |
| F2 | Hashing a password ran on the event loop: one sign-in stalled every other request on the worker, so a burst of sign-ins took the API down (found by the load test) | `app/auth.py` | fixed |
| F3 | Pooled database connections were opened with the 2 s timeout meant for the readiness probe; under load a slow connect answered 500 (found by the load test) | `app/main.py` | fixed |
| F4 | No limit on the size of a request body: a 1 GB JSON post was read whole | `app/bodylimit.py` | fixed |
| F5 | Webhook signing secrets, lead-intake secrets, Google and Meta tokens, tool keys are stored in the database unencrypted (carried from B10); a stolen dump or a read-only SQL leak exposes them | `app/models.py`, `docs/runbooks/backup-restore.md` | owner |
| F6 | Staff (platform admin) accounts sign in with a password alone; a stolen staff password opens every account | `app/auth.py` | owner |
| F7 | The live-call WebSocket takes the session token in its URL (browsers cannot set headers on a WebSocket), so a proxy that logs query strings stores tokens | `app/live.py` | accepted |
| F8 | Sign-up answers 409 for a registered email, which tells an attacker the address has an account | `app/auth.py` | accepted |
| F9 | Behind a reverse proxy every user looked like the proxy's address and shared one sign-in limit | `.env.example`, `docs/runbooks/deploy.md` | fixed |
| F10 | The Compose file publishes Postgres and Redis on the host with the password `axon` | `deploy/docker-compose.yml` | accepted |
| F11 | Sessions are one 12-hour JWT with no refresh and no server-side sign-out other than a password change | `app/auth.py` | accepted |
| F12 | The API sets no CORS headers, so a browser app on another origin cannot call it | `app/main.py` | accepted |
| F13 | The known-vulnerability scan of the dependencies could not run in the build sandbox (`api.osv.dev` is unreachable from it) | `.github/workflows/ci.yml` | fixed |

**F1.** Fixed-window counters in Redis: 10 sign-in tries per email and 100 per address per 15 minutes (a right password clears the email's count), 10 sign-ups per address per hour, 5 password-change tries per user per 15 minutes; the sixth answer is 429 with `Retry-After`. The count is taken before the check (one atomic step), so 30 parallel guesses get exactly 10 attempts, not 30; the lock is keyed on the typed email whether or not the account exists, and applies to the right password too, so it reveals nothing. With Redis down the attempt is still answered (Redis is already in the readiness probe). `test_auth_rate_limit.py`.

**F2, F3.** Found by `scripts/load_test.py` at 50 and 200 simultaneous users on a 4-core sandbox: a 500 from the 2 s connect timeout at 50 users. After the fixes both loads ran with 0 errors (numbers in `docs/runbooks/capacity.md`). The hashing fix is proven by `test_auth.py::test_hashing_a_password_does_not_stall_other_requests`, which fails with the hash on the loop and passes in a thread; on the sandbox the latency numbers barely moved because its four cores were the limit, so expect the gain on a host where hashing competes with other requests rather than with the load generator.

**F4.** `BodyLimit` refuses a body over 10 MB with 413, by `Content-Length` before reading it and by counting for chunked bodies or a client that lied. The largest honest body is a photo or PDF at 8 MB. Uploads were already read through size-limited readers; this covers every JSON route. `test_body_limit.py`.

**F5 (owner).** Encrypting these columns needs a library: `cryptography` is already in `uv.lock` (another package needs it) but is not listed in `docs/BUILD_PLAN.md` section 2 as a dependency of `axon-api`, and a key must live outside the database (an environment variable with a rotation plan). Options: (a) add `cryptography` and encrypt with Fernet under `AXON_SECRETS_KEY` (recommended before real customers; about a day's work including a migration that re-encrypts), or (b) accept for the beta and rely on encrypted backups and database access control. Until decided: dumps must be kept encrypted ([backup-restore.md](../runbooks/backup-restore.md)).

**F6 (owner).** A second factor for staff (TOTP) is a new feature, so it is the owner's call. Until then: few staff, long unique passwords, and staff accounts kept in a company of their own.

**F7.** The token lasts 12 hours. Runbook: do not log query strings at the proxy. A short-lived one-use ticket for the socket is a Track 2 improvement.

**F8.** Standard sign-up behaviour (the alternative is an email round trip). Mass probing is limited by F1.

**F9.** `FORWARDED_ALLOW_IPS` is documented in `.env.example` and the deploy runbook, and a missing one is an incident-table entry.

**F10.** It is the development stack. The deploy runbook says to publish only the API and engine behind TLS and to use private networking and real passwords.

**F11.** A stolen token works until it expires or the user changes their password. Revocation by password change exists since B13. A token list or shorter lives with refresh is a Track 2 session-design decision.

**F12.** The dashboard (Track 2) will be same-origin or add an allow-list for its own origin; a wildcard must never be added.

**F13.** CI has a non-blocking `audit` job running `uv audit --locked`; its first run (PR 16) found no known vulnerabilities and no adverse project statuses in 99 packages. Read its output on each PR.

## Checked, nothing found

| Check | How |
|---|---|
| Every operation refuses an anonymous caller, except a listed set of public routes, each with its reason | `test_route_security.py` sweeps every operation in the OpenAPI spec; the public routes are sign-up, sign-in, the two probes, the API reference, and the webhooks and one-time pages below. A route added without authentication fails the test (negative control run) |
| Every `/admin` route refuses a signed-in non-staff user | same file |
| A dashboard session does not open the public API and an API key does not open the dashboard | same file |
| Inbound webhooks check their proof and compare in constant time (`hmac.compare_digest`) | Vobiz events, Razorpay, Meta (handshake and signature), the lead-intake secret, the one-time phone code |
| A customer-chosen URL cannot reach private addresses (the HTTP tool, account webhooks, the result webhook) | all go through `app/actions/net.py` (tested since B10, NAT64 added in B10 review) |
| Uploads are size-limited before they are read | audio 2 MB, photo or PDF 8 MB, text 200 KB, CSV 5 MB; plus F4 |
| Recordings are served by 15-minute presigned links | `app/providers/storage/r2.py` |
| No secret in the repository or in a log line | pattern scan over tracked files (one AWS documentation example in a test); grep of logging calls |
| Containers run as a non-root user | `deploy/Dockerfile` (uid 10001) |
| Tenant scoping: another account's id answers 404 | each router's tests since B4 (reviewed per phase); not re-swept here |
| Staff support sessions cannot reach `/admin`, change the password or set up anything that outlives them | B13 |
| Error bodies do not leak internals | vendor errors name only the host; unhandled errors are a bare 500 |
