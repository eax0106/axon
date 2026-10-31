# Plan — status board

Owner: Havish. Orchestrator updates this file after every merge.

Legend: `todo` · `building` · `in review` · `changes` · `merged` · `blocked`

## Track 1 — Backend (in order)

| Phase | Title | Builder | Status | PR | Notes |
|---|---|---|---|---|---|
| B0 | Foundation (monorepo, Docker Compose, CI on 3 OSes, settings, provider registry) | Opus | merged | [#1](https://github.com/eax0106/axon/pull/1) f1a5f18 | 2 review rounds; L1 admin-gate carried to B1 |
| B1 | Data model + auth | Opus | merged | [#2](https://github.com/eax0106/axon/pull/2) 0da5c82 | 2 review rounds; carry-overs B7 ledger idempotency, B13 token revocation, B14 rate limit |
| B2 | Voice engine (Pipecat, Vobiz serializer) | Opus | merged | [#3](https://github.com/eax0106/axon/pull/3) 6cfe998 | 2 review rounds + image-size and end-of-call ordering fixes; carry-overs in docs/phases/b2.md |
| B3 | Speech + LLM provider adapters | Sonnet | merged | [#4](https://github.com/eax0106/axon/pull/4) dd356c0 | 2 review rounds; STT fixtures to regenerate with licensed TTS at wiring |
| B4 | AI employee builder | Sonnet | merged | [#5](https://github.com/eax0106/axon/pull/5) 864401d | 2 review rounds; carry-overs in docs/phases/b4.md |
| B5 | Instant channel | Sonnet | merged | [#7](https://github.com/eax0106/axon/pull/7) b9ca988 | 2 review rounds; carry-overs in docs/phases/b5.md |
| B6 | Post-call + data views | Sonnet | merged | [#8](https://github.com/eax0106/axon/pull/8) f44a952 | 3 review rounds (Indic quote normalisation); carry-overs in docs/phases/b6.md |
| B7 | Billing + numbers (incl. number types and dialer rule table) | Sonnet | merged | [#9](https://github.com/eax0106/axon/pull/9) 654604b | 2 review rounds (billing stall, unknown purchase result, channels, alert on every spend); carry-overs in docs/phases/b7.md |
| B8 | Bulk campaigns | Sonnet | merged | [#10](https://github.com/eax0106/axon/pull/10) d542e77 | 3 review rounds (callback on a campaign's last call, naive start time, resume of a scheduled campaign); B7 free-channel carry-over done. Waiting on the owner: defaults of 2 calls at once, 2 retries an hour apart, 7-day dedupe, and the consent re-confirm rule (contacts added after consent pause the campaign until it is confirmed again). Details in docs/phases/b8.md |
| B9 | Inbound | Sonnet | merged | [#11](https://github.com/eax0106/axon/pull/11) 1482b5b | 1 review round (a transfer closed the call before Vobiz fetched the instructions; a retried answer-URL fetch logged a false busy miss; channel not held during a transfer; orphan queued call for a Bulk employee). Waiting on the owner: native-speaker check of the Telugu and Hindi default greetings and recording notice; a fully verified Vobiz account is needed for inbound. Details in docs/phases/b9.md |
| B10 | In-call actions | Sonnet | merged | [#12](https://github.com/eax0106/axon/pull/12) c889d87 | 1 review round (a masked secret followed an action to another host, the AI edit flow sent secrets to the model and wiped the actions, NAT64 addresses passed the network guard). Waiting on the owner: whether members may use the Google connection (only the owner changes Sheets actions for now). Follow-ups: members can still change the Calendar id; static HTTP headers are not masked. Details in docs/phases/b10.md |
| B11 | Training + knowledge | Sonnet | merged | [#13](https://github.com/eax0106/axon/pull/13) db28c35 | 1 review round (a half-read PDF or photo was saved as complete, the text cleaner stripped ZWJ/ZWNJ and split Telugu and Hindi words, a CSV under 60,000 characters could be refused for passage count). Open owner questions: should teaching be owner-only (today it follows the employee's normal edit rights), and tune the 0.55 relevance threshold on real documents (WIRING item 27). Details in docs/phases/b11.md |
| B12 | Developer platform (API keys, webhooks) | Sonnet | merged | [#14](https://github.com/eax0106/axon/pull/14) 1b1c1ca | 1 review round (leads made by a bulk campaign never emitted lead.created because a Core insert skips the flush hook; the call-scan index kept test and cancelled calls); carry-overs in docs/phases/b12.md. Owner questions: members may set the result webhook (like scripts) until answered; OpenAPI is checked by our own tests, a validator library needs approval |
| B13 | Reliability + admin | Opus | merged | [#15](https://github.com/eax0106/axon/pull/15) 77f57cf | 2 review rounds (a support session could set up webhooks, actions, the result webhook (also through the script), a Google connection, the lead-intake secret or a transfer number that outlive it; a refund of a purchase with no charge on record claimed success; cheapest-tier billing now compares the configured rates). Waiting on the owner: native-speaker check of the Hindi and Telugu apology; may members add do-not-call numbers (only owners remove). Staff must enter vendor rates and balances; the 100-call capacity default waits for the B14 load test. Details in docs/phases/b13.md |
| B14 | Hardening + parity check | Sonnet | merged | [#16](https://github.com/eax0106/axon/pull/16) aadc0ba | 1 review round, APPROVE; non-blocking follow-ups merged in [#17](https://github.com/eax0106/axon/pull/17) d642d8f (F14, owner-only dumps, WebSocket sweep). Waiting on the owner: encrypt stored secrets at rest (F5, adds `cryptography` as a direct dependency) and a second factor for staff sign-in (F6). Security review, parity audit, runbooks and the Track 1 summary are in docs/phases/ and docs/runbooks/. Details in docs/phases/b14.md |
| SEC | Security test of the full backend (Strix dropped by owner; done by Claude) | Opus | merged | [#18](https://github.com/eax0106/axon/pull/18) 9dd19b2 | No Critical or High; S1–S5 (Medium, Low) fixed on owner request. 1 review round (number channels and the hourly spend cap were still open to a support session), then APPROVE; merged on the owner's yes. Non-blocking follow-ups: a test for the Redis-down nonce branch, a format check on the CallUUID before it goes into the carrier URL. Details in docs/phases/sec.md |

## Track 2 — Frontend (after Track 1 + SEC)

Opus builder only (medium effort for UI and UX work, owner rule 2026-10-30). Plan approved by the owner on 2026-10-30, with the dependency list, team invites left out of F11, and an "Axon" wordmark until a logo exists.

| Phase | Title | Status | PR | Notes |
|---|---|---|---|---|
| F1 | Foundation, contracts, app shell | merged | [#19](https://github.com/eax0106/axon/pull/19) 8898cca | |
| F2 | Sign-up, sign-in, account basics | merged | [#20](https://github.com/eax0106/axon/pull/20) c351f04 | |
| F3 | AI employee builder | merged | [#23](https://github.com/eax0106/axon/pull/23) d9aeed7 | |
| F4 | Test calls and the live-call view | merged | [#24](https://github.com/eax0106/axon/pull/24) bfe35f6 | |
| F5 | Credits, billing, numbers, KYC, go live | in review | | completes the guided first run |
| F6 | Dashboard, conversations, leads | todo | | |
| F7 | Instant | todo | | |
| F8 | Bulk campaigns | todo | | |
| F9 | Inbound | todo | | |
| F10 | Training, knowledge, in-call actions | todo | | |
| F11 | Developers, settings, support | todo | | |
| F12 | Staff admin console | todo | | |
| F13 | Help centre, integration guides, final parity and quality pass | todo | | |

### Rules that hold in every F phase

- **Loop:** branch `phase/fN-<slug>` from latest `main`; gates in `.unlazy/axon/gates/fN.md` before building; ponytail for all code; `/verify` before every commit; `docs/phases/fN.md`; PR with screenshots; then `/thermo-nuclear-code-quality-review` as a separate pass and its findings fixed; merge only on the owner's yes. Next phase only after merge.
- **Real API only.** Every screen talks to the local Compose backend through the generated client. No mock data in the product. A `503 provider_not_configured` renders a calm "Connect <provider> to use this" panel naming the missing key; any other error shows a retry state. Nothing crashes.
- **UX beats visuals.** Daily screens (lists, call logs, leads, settings) never have an entrance longer than 300 ms or any animation that blocks input. Showpiece motion only on first run, empty states, the live-call view and rare moments. Hover and state changes 150–300 ms. `prefers-reduced-motion` gets instant fades and a static orb.
- **States.** Every data view has skeleton, empty, error and 503 states. Mutations are optimistic where the API allows a safe rollback.
- **Keyboard and phone.** Visible mint focus ring, Radix primitives for every overlay and control, every flow usable at 375 px wide.
- **Indic text.** Telugu, Hindi and English render with Noto fallbacks; ZWJ/ZWNJ are never stripped (no text normalisation in the client).
- **Per-phase "done when" (always, on top of the phase's own list):** `pnpm typecheck`, `pnpm test` and `pnpm build` green on CI (macOS, Windows, Linux); every flow of the phase clicked through in a browser against the Compose stack, with screenshots (desktop and 375 px) in the PR; axe check shows no serious or critical issue on the phase's screens; route chunk for the phase lazy-loaded; no new frame drops in a performance trace of the phase's showpiece.

### F1 — Foundation, contracts, app shell
- **Builds:** `apps/web` (Vite + React + TS strict, Tailwind with every DESIGN_DIRECTION §2 token as a CSS variable, nothing else), `motion.ts` (all durations and easings), fonts (Manrope, Inter, Noto Sans Telugu and Devanagari, self-hosted), pnpm workspace pinned to a pnpm version that runs on Node 20 LTS. `packages/contracts`: `openapi.json` exported from the FastAPI app by a Python script, TS types generated from it, and a CI check that both are fresh. API client with bearer auth, 401 handling and the 503 provider state. App shell: left rail (DESIGN_DIRECTION §7), top bar with credit chip, live-calls indicator, notifications bell, ⌘K palette (navigation only for now), page cross-fade, light/dark toggle. `web` service in Compose (static build served by a small web server that proxies `/api` and the WebSocket to the API). CI job for the web app on 3 OSes. Contrast check script for every token pair.
- **APIs:** `/accounts/me`, `/wallet`, `/notifications`, `/healthz`.
- **Done when:** `docker compose up` serves the shell at its port and the shell reads real data after sign-in (token pasted by hand until F2); regenerating the client from a changed schema makes CI fail until committed; every text and chart colour pair passes 4.5:1 (3:1 for large text and chart marks) in both themes; first load under 150 KB gzip JS.
- **Backend touch:** fix the duplicate OpenAPI operation id on `POST /public/otp/{token}` so the client generates cleanly (one-line change in `phone_verify.py`).

### F2 — Sign-up, sign-in, account basics
- **Screens:** sign-up (with terms acceptance), sign-in, sign-out, rate-limit and wrong-password states, owner-phone verification by one-time code, notifications drawer (read, read all), hero headline cycling on the auth screens.
- **APIs:** `/auth/signup`, `/auth/login`, `/account/terms`, `/accounts/me`, `/accounts/owner-phone`, `/accounts/owner-phone/verify`, `/notifications*`.
- **Done when:** a new owner signs up, lands in the shell with 50 free credits shown, verifies their phone; a wrong password and the 429 limit show plain messages; the session survives reload and a 401 returns to sign-in without losing the page they were on.

### F3 — AI employee builder
- **Screens:** Employees list (status, channel, number), Hire flow (channel, languages, brief typed or spoken with a live waveform, follow-up questions, draft that "materialises" section by section), employee detail tabs Script (welcome, sections reorder/edit/delete, end rules, permanent FAQ, strictness 1–5, pre-call and captured variables, AI edit flow), Voice (tier, picker with preview, speed, ambience and volume), Channel settings (toggles: style pack, power prompting, AI disclosure), Versions (perspective card deck of the last 3, restore). Publish bar ("Apply to live calls", discard) for gated edits; instant-apply edits save on change. Duplicate, switch channel, start over, pause/activate, delete.
- **APIs:** `/employees*` (create, patch, script, settings, publish, revert, versions, restore, duplicate, switch-mode, reset, activate, deactivate, prompt), `/ai/*`, `/voices*`.
- **Done when:** an owner goes from "Hire" to a drafted, edited and published employee; reorder, restore and discard round-trip through the API; the spoken brief works with the mic and shows the 503 state when speech-to-text has no key; the draft step shows the 503 state without an LLM key and still lets the owner write the script by hand.

### F4 — Test calls and the live-call view
- **Screens:** chat sandbox, browser web call (mic to the engine's `/web/stream`) with the **Live Call Orb** (react-three-fiber, reacts to real audio amplitude), phone test call to the owner's verified phone, and the shared **live-call view**: pipeline stepper (ringing, listening, thinking, speaking, capturing, done) driven by `/calls/{id}/live`, streaming transcript with mint caret, captured fields flying into a hairline list, pulsing "on a call" state. The view is reused by Instant, Bulk and Inbound later.
- **APIs:** `/employees/{id}/chat`, `/employees/{id}/web-test-call`, `/employees/{id}/test-call`, WebSocket `/calls/{id}/live`.
- **Done when:** the chat sandbox answers (or shows the LLM 503 state); the web call connects the mic to the engine and the orb reacts to real input level; the live view renders a real event stream from the Redis channel end to end (proved by a test that publishes events the way the engine does); the orb holds 60 fps on a mid laptop and pauses on hidden tabs; reduced motion shows a static orb.

### F5 — Credits, billing, numbers, KYC, go live
- **Screens:** Billing (balance, credits runway meter with spend sparkline, top-up presets and custom amount through Razorpay checkout, spend cap and alert settings, statements this and last month, transactions with running balance, per-employee usage, GST invoices), Numbers (store search, quote, purchase, KYC by PAN then DigiLocker, verified holder reused, channels, renewal and grace status, release), attach a number to an employee, go live. **Guided first run** finished here: sign-up, hire, test, number, live, as one checklist that disappears when done.
- **APIs:** `/wallet*`, `/billing/*`, `/numbers*`, `/employees/{id}/number`, `/employees/{id}/activate`.
- **Done when:** a new account walks the first-run checklist to the point the keys allow and each blocked step shows which provider to connect (Razorpay, Vobiz); ledger, statement and invoice screens match the API numbers to the paisa; the runway meter animates only when the balance changes.

### F6 — Dashboard, conversations, leads
- **Screens:** Dashboard and Performance (channel split, connect / qualify / conversion %, best hour, leaderboard, within-60-s speed, 7/30/90-day and custom ranges, rich charts in SVG), Conversations (all filters, remembered filters, CSV export), call detail (timeline, recording player, transcript in the call's script, summary, sentiment, captured fields, notes, share summary, re-analyse), Leads (table, cards and kanban by outcome, notes, export with a field picker, caller memory reset), ⌘K search over employees, leads and calls.
- **APIs:** `/stats/overview`, `/calls*`, `/me/filters/conversations`, `/leads*`, `/notes/{id}`, `/account/caller-memory*`.
- **Done when:** filters survive a reload; 1,000 calls scroll smoothly (list virtualised or paged by the API); kanban moves a lead with an optimistic update and rolls back on error; exports download the API's CSV unchanged; Telugu and Hindi transcripts render with joiners intact.

### F7 — Instant
- **Screens:** intake URL and secret (reveal, rotate), website snippet, intake log, test lead, dialer settings (delay, window inside 6 AM–10 PM, out-of-window rule, retry ladder up to 9 steps), **queue lanes** (waiting with countdown ring, dialing, on call, done), redial, cancel, one-off call, Meta Lead Ads form setup, Google Sheets source.
- **APIs:** `/employees/{id}/instant*`, `/lead-intake/meta`, `/integrations/google*`.
- **Done when:** a test lead appears in the log and the queue without a real call; window and ladder limits are enforced in the form with the API's own errors shown in place; lanes animate with layout motion under 300 ms and never block clicks.

### F8 — Bulk campaigns
- **Screens:** campaign list, create (contacts by CSV, paste or manual; column mapping with preview and no guessing; saved lists), settings (window 9 AM–9 PM, days, holidays, concurrency 1–20, skip DNC, retries, schedule and repeat, dedupe window, exclusions), consent confirmation (statement shown word for word), capacity preview, **campaign constellation** live panel with rolling counter, every live action, analytics, export.
- **APIs:** `/campaigns*`, `/contact-lists*`.
- **Done when:** a CSV with Telugu names imports with an exact mapping preview; a campaign cannot be started without consent and says why; the live panel tracks the API state and its actions update it optimistically; the constellation stays at 60 fps with 2,000 contacts.

### F9 — Inbound
- **Screens:** inbound settings (connect the number, 24/7 or opening hours as weekly IST windows, closed behaviour, greetings for new and returning callers, recording notice editable but never removable, transfer number and condition, answer own call-backs, daily summary), messages and call-backs with a done tick, missed callers with plain reasons, "answering now" state with the orb.
- **APIs:** `/employees/{id}/inbound-settings`, `/employees/{id}/inbound/connect`, `/inbound/messages*`, `/inbound/missed`.
- **Done when:** hours that cross midnight are offered as two windows; the recording notice cannot be blanked; marking a message done is optimistic and reversible.

### F10 — Training, knowledge, in-call actions
- **Screens:** Training tab (teach by text, voice or photo; review proposals before saving; facts and rules list with limits shown; documents upload, list, delete, search test; struggle suggestions quoting the call, accept or dismiss), Actions tab (Google Calendar, Sheets, custom HTTP with test console, WhatsApp; opt-in per employee; publish-gated with the script), Google connection with the granted services shown, result webhook tab.
- **APIs:** `/employees/{id}/training*`, `/employees/{id}/actions*`, `/integrations/google*`, `/employees/{id}/webhook*`.
- **Done when:** nothing is taught without the review step; a cut-off photo reading shows the API's refusal; action secrets are never shown back (mask only); action edits wait for publish.

### F11 — Developers, settings, support
- **Screens:** Developers (API keys create/revoke with the key shown once, webhooks with events, rotate secret, test, delivery log and resend, request log, status, OpenAPI and Postman downloads), Settings (name, business name, max call length, password change, caller memory, do-not-call list with single and bulk add and owner-only removal, terms), support chat, feedback and rating.
- **APIs:** `/developer/*`, `/account/settings`, `/auth/password`, `/dnc*`, `/support/*`, `/v1/openapi.json`, `/v1/postman.json`.
- **Done when:** a new key and a new webhook secret are shown exactly once with a copy button; owner-only actions are hidden or disabled for members with the reason; a password change signs the user in again cleanly.
- **Team:** see owner question 2.

### F12 — Staff admin console
- **Screens:** separate staff area (only for staff users): accounts, account detail, logged impersonation with a reason and an always-visible "support session" banner, credit adjustments, voice library, provider health, costs, rates and balances, carrier capacity, system health, revenue, dial-rule table, Instant policy, number settle, announcements, alerts, support inbox and replies.
- **APIs:** `/admin/*`.
- **Done when:** a non-staff user never sees or loads the admin chunk; an impersonation shows the banner on every page and ends cleanly; every admin write shows what it changed.

### F13 — Help centre, integration guides, final parity and quality pass
- **Builds:** in-app help centre (our own words) including the website POST, Meta, Sheets, n8n, Make, Zapier and Pabbly guides that use our real intake URL, API and webhooks; empty states with the hero cycling line; Playwright end-to-end run of the main flows against the Compose stack; full axe, keyboard and 375 px sweep; bundle and frame-rate audit; PARITY.md "Outside the backend" rows for the guides and the dashboard ticked.
- **Done when:** PARITY.md has no open UI or help item; the Playwright suite passes on CI; Lighthouse performance and accessibility each at least 90 on the dashboard, call list and live-call view.

### Owner questions before F1
1. **Dependencies outside BUILD_PLAN §2** that I need (all small, MIT): `react-router` (routes, code-splitting), `@tanstack/react-query` (caching, optimistic updates), `openapi-typescript` + `openapi-fetch` (typed client from our schema), `@fontsource` packages for the four fonts (self-hosted, no Google CDN), `vitest` + `@testing-library/react` (tests), `@playwright/test` and `@axe-core/playwright` (end-to-end and accessibility checks), and `three` (required by react-three-fiber). No chart, table, icon or command-palette library: charts are hand-built SVG, the palette is a Radix dialog. Approve the list?
2. **Team:** the backend has owner and member roles but **no API to invite or remove team members**. Recommendation: F11 shows account settings only, and team invites become a small backend phase later. Or add that backend work now?
3. **Logo:** DESIGN_DIRECTION §8 says the ALTERX mark is not reused unless you confirm. Use "Axon" as a wordmark in Manrope until a logo exists?

## Track 3 — Wiring and launch

See `docs/WIRING_CHECKLIST.md`.

## Prerequisites before B0

- [x] Write access on `eax0106/axon` (account havishvardhan04-creator)
- [x] Repo stays public (owner, 2026-10-24)
- [x] Project folder created: `~/Desktop/Projects/axon-voice-engine`
- [x] Docs, rules and hooks in place
