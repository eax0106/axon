# SEC — Security test of the running backend

Branch `phase/sec-strix`, cut from `main` at `3262152` (B14 and its follow-up PR merged). Gate ledger: `.unlazy/axon/gates/sec.md` (untracked).

**Method.** The phase was planned as a Strix run. Strix was not used: on 2026-10-28 the owner chose to have the test done by Claude directly instead. It was a black-box test of the whole Compose stack (`api`, `engine`, `worker`, Postgres, Redis), run on the owner's Mac against `localhost` only, with no vendor keys set, so no request reached a third party. The stack ran as its own Compose project (`axon-sec`, fresh volume) and was seeded through the public API with two tenant owners, one staff admin (`users.is_platform_admin` set as in `docs/runbooks/deploy.md`), an API key and an employee per tenant, plus a lead, campaign, contact list and webhook endpoint for the second tenant. The probe scripts (Python, `httpx`, plus the `websockets` client inside the engine container) were run from a scratch folder and are not committed. Every finding below was re-checked by hand against the code.

This does not repeat the B14 code review (`b14-security-review.md`). Its open owner items F5 (stored secrets unencrypted) and F6 (no second factor for staff) are not repeated here.

## Coverage

| Area | What was tried | Result |
|---|---|---|
| Auth | Anonymous calls to dashboard, developer and admin routes; a malformed token; an unsigned `alg: none` token | All 401 |
| Tenant isolation (dashboard) | Owner A's session sent to every route that takes an id (120 operations, all methods including PATCH and DELETE) with owner B's real ids from the database | 0 answered 2xx. Positive control: owner B on the same ids got 2xx on 15 GET routes, so the sweep can see a leak |
| Tenant isolation (public API) | A's API key on B's employee (read and lead create) | 404 |
| API keys | API key on the dashboard; dashboard session on `/v1`; a key with its last characters changed | All 401 |
| Admin | Non-staff owner on `/admin/accounts`, `/admin/system`, `/admin/providers` | 403; staff gets 200 |
| Impersonation | Staff support session on `/admin`, API key create, webhook create, intake secret reveal and rotate, password change | 403 for all of these. Gaps: S1, S2, S3 |
| Impersonation sweep | Every non-admin POST, PUT and PATCH route called from a support session with an empty body: a route guarded by `not_impersonating` answers 403 before the body is read; anything else is reachable | 91 routes reachable; the ones that matter are S1 to S3 below (the rest are ordinary edits a support session is meant to make, or 404 for an id that does not exist) |
| Intake URLs and secrets | Website intake with no secret, a wrong secret, an unknown connection id | 401, 401, 404 |
| Inbound webhooks | Razorpay, Vobiz events and Meta lead webhooks with bad signatures; Meta handshake with a wrong verify token | 503 `provider_not_configured` (no vendor keys on this stack). The signature checks are covered by unit tests since B5 to B10; they were not exercised live |
| SSRF guards | Account webhook URLs `127.0.0.1`, `localhost`, `[::1]`, `10.0.0.1`, `169.254.169.254`, the Compose hostname `postgres`, `0x7f000001`, `2130706433`, `file://` | All refused with 422 at create |
| File upload and body size | 9 MB photo; 12 MB JSON body; a multipart body to a raw-body upload route | 413, 413, 415 |
| CSV export | Cells starting with `=`, `+`, `-`, `@` | Escaped by `app/calls/csvsafe.py` on all three exports (code check; a live intake lead needs a live employee and a number) |
| Rate limits | 12 wrong sign-ins for one email | 401 ten times, then 429 |
| Engine HTTP | `/vobiz/transfer` and `/vobiz/transfer-result` with a forged ticket; `/vobiz/answer` for another tenant's unpublished employee; `/vobiz/inbound` | 403, 403, 404, 503 |
| Engine WebSocket | `/web/stream` with a forged ticket; `/vobiz/stream` for an unpublished employee; `/vobiz/stream` with no employee | Closed 1008, 1008, 1011 (`provider_not_configured`). With keys set, `/vobiz/stream` also refuses a call the carrier does not report live |

## Findings

No Critical or High finding. Medium and Low findings are for the owner's decision; none was fixed in this phase.

| # | Severity | Finding | Where | Proof | Verdict |
|---|---|---|---|---|---|
| S1 | Medium | A staff support session can rotate a developer webhook's signing secret and is shown the new secret. The staff member can then sign fake events that the customer's server accepts, and the customer's own verification breaks at once | `app/developer/router.py` `rotate_secret` (no `not_impersonating`) | Live: owner creates an endpoint; the support session's `POST /developer/webhooks/{id}/rotate-secret` answered 200 with a `secret`. Creating or editing a webhook in the same session answers 403 | Real |
| S2 | Medium | A support session can connect a Meta lead form or a Google Sheet to an Instant employee. Both outlive the session and make the employee call people on the account's credit, which `refuse_in_support_session` says a support session must not set up | `app/instant/router.py` `connect_meta`, `sheets_connect`, `sheets_choose` | Live: the sweep's support-session calls reached body validation (422) instead of 403. By code: the only other checks are the vendor's own (Meta token can read the form, Google OAuth code), which a staff member with their own Meta page or Google account passes | Real |
| S3 | Medium | Other money and identity actions are open to a support session: buy a number (`POST /numbers/purchase`), submit KYC (`/numbers/kyc/*`), start a wallet top-up, set and verify the owner's phone (`/accounts/owner-phone*`), and point an employee at a number (`PUT /employees/{id}/number`). Each is audited as a support-session change. Whether support staff may do these on a customer's behalf is a product call | `app/numbers/`, `app/billing/`, `app/phone_verify.py` | Live: all reached validation (422) in a support session | Real, policy |
| S4 | Low | `/vobiz/inbound` on the engine is unsigned and takes `To` and `From` from the request. A request is only believed when the carrier reports its `CallUUID` live, so a forger needs a live call id; with one, they could have a call recorded against another number than the one dialled | `engine/main.py` `vobiz_inbound`, `app/inbound/routing.py` `route` | By code (503 on this stack without Vobiz keys). Fix would be to verify the Vobiz V3 signature as `/vobiz/events` does, or to read `To` and `From` from the carrier's call record | Real, needs a live carrier call |
| S5 | Low | The Vobiz V3 signature covers the URL and a nonce but no time, and used nonces are remembered for 5 minutes in one process. A captured `/vobiz/events` callback can be replayed later or to another API replica. The body is not trusted (the outcome comes from the carrier's record), so a replay only re-runs an idempotent settle | `app/instant/public.py` `_seen_nonces` (already marked `ponytail:` in code) | By code | Real, no impact found |

**Not findings.** The default Compose project's `pgdata` volume on the owner's Mac is stamped at migration `0012` but lacks `users.is_platform_admin`, so sign-up answers 500 there. That volume predates a change to an earlier migration; a fresh volume migrates cleanly. It is a stale development database, not a product defect, and it was left untouched.

## For the owner

1. **S1 and S2:** recommended to add `not_impersonating` to `rotate_secret`, `connect_meta`, `sheets_connect` and `sheets_choose` (one line each, plus one support-session test). This matches the rule the code already states.
2. **S3:** decide whether support staff may buy numbers, submit KYC, top up or change the owner's phone while acting as the owner. If not, the same one-line guard applies.
3. **S4 and S5:** recommended to verify the signature on `/vobiz/inbound` when Vobiz keys are wired (Track 3), and to move the nonce store to Redis when the API runs more than one replica.
