# Track 1 summary — Axon backend, B0 to B14

Status: Track 1 (the backend) is built, reviewed and merged phase by phase, B0 to B13 on `main`, B14 in [PR 16](https://github.com/eax0106/axon/pull/16). Next: the SEC phase (Strix), then Track 2 (the dashboard), then Track 3 (keys and real calls). Details per phase are in `docs/phases/bN.md`; the live status board is `docs/PLAN.md`.

## What was built

| Phase | What | PR | Review rounds |
|---|---|---|---|
| B0 | Monorepo, Docker Compose, CI on Linux, macOS and Windows, settings, provider registry, `/admin/providers` | [#1](https://github.com/eax0106/axon/pull/1) | 2 |
| B1 | Full data model (accounts, employees, calls, leads, ledger, keys, audit...), migrations, own email and password auth with argon2 and JWT, roles | [#2](https://github.com/eax0106/axon/pull/2) | 2 |
| B2 | Voice engine on Pipecat: our Vobiz serializer, barge-in, Indic sentence splitting, call-length cap, recording, cost meter, live events | [#3](https://github.com/eax0106/axon/pull/3) | 2 |
| B3 | Speech and LLM adapters (Sarvam, Smallest, Cartesia, Gemini), voice tiers Value, Standard, Premium | [#4](https://github.com/eax0106/axon/pull/4) | 2 |
| B4 | AI employee builder: brief, draft, script editor, strictness, variables, prompt compiler, lifecycle, publish gate, three versions, test calls | [#5](https://github.com/eax0106/axon/pull/5) | 2 |
| B5 | Instant channel: intake URL and secret, dialer rules, retry ladder, queue console, Meta Lead Ads, Google Sheets | [#7](https://github.com/eax0106/axon/pull/7) | 2 |
| B6 | Post-call analysis ("nothing invented"), conversations, leads, caller memory, callbacks, stats, notifications | [#8](https://github.com/eax0106/axon/pull/8) | 3 |
| B7 | Billing and numbers: credit ledger, per-second metering, Razorpay, GST invoices, number store, KYC, renewals, number types and the dial rule table | [#9](https://github.com/eax0106/axon/pull/9) | 2 |
| B8 | Bulk campaigns: CSV import, windows, concurrency, retries, schedule, dedupe, consent, live panel | [#10](https://github.com/eax0106/axon/pull/10) | 3 |
| B9 | Inbound: answering, hours, greetings, messages, missed callers and call-back, transfer to a human, daily summary | [#11](https://github.com/eax0106/axon/pull/11) | 1 |
| B10 | In-call actions: Google Calendar and Sheets, custom HTTP tool, WhatsApp | [#12](https://github.com/eax0106/axon/pull/12) | 1 |
| B11 | Training and knowledge: facts and rules by text, voice or photo, documents, struggle detector | [#13](https://github.com/eax0106/axon/pull/13) | 1 |
| B12 | Developer platform: API keys, public API, OpenAPI, Postman, signed webhooks, result webhook | [#14](https://github.com/eax0106/axon/pull/14) | 1 |
| B13 | Reliability and admin: mid-call failover, health scoring, capacity, admin console APIs, support sessions, settings, DNC | [#15](https://github.com/eax0106/axon/pull/15) | 2 |
| B14 | Hardening: auth rate limits, route security sweep, request limits, backups, load test, runbooks, security review, parity audit, terms acceptance | [#16](https://github.com/eax0106/axon/pull/16) | see the PR |

## Numbers

- **Parity:** `docs/PARITY.md` has 73 backend rows, all ticked, each mapped to routes and tests in `docs/phases/b14-parity-audit.md` (a test enforces it). Three items are outside the backend and not counted: the five licensed ambience sound files (an asset), the n8n, Make and Zapier guides (Track 2 content) and the admin and dashboard UI (Track 2).
- **API:** 234 operations. Every one is swept by a test for anonymous access (the live-call WebSocket has its own sweep entry; the engine's two sockets are covered in the engine tests), and every `/admin` one for non-staff access.
- **Tests:** 1,251 pass and 65 are skipped on purpose (B14 run). Everything that needs a vendor key is tagged `requires_keys` and is the only thing skipped.
- **Gates:** each phase has a gate ledger of runnable checks (B8: 18, B9: 19 with its CI gates, B10: 19, B11: 19, B12: 21, B13: 20, B14: 16); a phase merged only with every gate met, CI green on Ubuntu, macOS and Windows plus the Compose job, and a reviewer's approval. Earlier ledgers were not kept in the repository.
- **Load:** 50 simultaneous users, 12,000 requests, no errors (`docs/runbooks/capacity.md`; the call side waits for vendor keys).

## Open items

**For the owner to decide** (nothing blocks the next step):

- B8: defaults of 2 calls at once, 2 retries an hour apart, a 7-day dedupe window, and the rule that contacts added after consent pause a campaign until it is confirmed again.
- B10: may members use the account's Google connection (only the owner changes Sheets actions today)?
- B11: should teaching be owner-only (today it follows the employee's edit rights)? The 0.55 relevance threshold needs tuning on real documents (WIRING #27).
- B12: may members set an employee's result webhook (today they can, like scripts)? An OpenAPI validator library would need approval; the spec is checked by our own tests.
- B13: may members add do-not-call numbers (today they can; only owners remove)? Staff must enter vendor rates and balances (WIRING #30).
- B14: encrypt stored secrets at rest (adds `cryptography` as a direct dependency and a key) and add a second factor for staff sign-in (F5, F6 in `docs/phases/b14-security-review.md`; WIRING #35).

**Needs people:** native-speaker checks of the Telugu and Hindi default greetings and recording notice (B9), the apology a caller hears on our fault (B13, WIRING #29), and voice quality in all three languages; a fully verified Vobiz account for inbound.

**Needs real calls:** reply time under one second per language, the capacity number for `AXON_MAX_CONCURRENT_CALLS`, failover on real vendors, the null rate of captured fields in Telugu and Hindi, voicemail detection, the relevance threshold.

## Keys and accounts needed next

Full list with the variable name for each: `docs/WIRING_CHECKLIST.md` (36 items). In order of what unlocks the most:

1. **Vobiz** (auth id and token, a number, KYC access, a public https URL for the API and the engine): every call.
2. **Sarvam, Gemini, Smallest, Cartesia** API keys: speech, language model, voices, document search.
3. **Cloudflare R2** and a domain: recordings, public URLs.
4. **Razorpay** test keys and webhook; a **Resend** domain for email.
5. **Google Cloud OAuth client** (Calendar and Sheets; Google's verification before real customers), a **Meta** app for Lead Ads, **Interakt or AiSensy** with approved templates.
6. **Hosting** in an India region; test phones; Telugu and Hindi speakers.
7. For the security phase: a **Strix** LLM key and the roughly 5.8 GB image (owner approval).
8. Business paperwork: company and GST, the legal opinion on TRAI number series and DPDP, and the terms text.

## What comes after

1. **SEC:** Strix against the running backend; fixes go through the same build and review loop.
2. **Track 2:** the dashboard on the real API, the admin console UI, the help-centre guides.
3. **Track 3:** keys in, contract tests (`requires_keys`) become mandatory, first real calls, latency tuning per language, hosting, a beta on your own number.
