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

Phases are defined by the orchestrator when Track 2 starts. Opus builder only.

## Track 3 — Wiring and launch

See `docs/WIRING_CHECKLIST.md`.

## Prerequisites before B0

- [x] Write access on `eax0106/axon` (account havishvardhan04-creator)
- [x] Repo stays public (owner, 2026-10-24)
- [x] Project folder created: `~/Desktop/Projects/axon-voice-engine`
- [x] Docs, rules and hooks in place
