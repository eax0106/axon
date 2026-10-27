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
| B11 | Training + knowledge | Sonnet | in review | [#13](https://github.com/eax0106/axon/pull/13) | Details in docs/phases/b11.md |
| B12 | Developer platform (API keys, webhooks) | Sonnet | todo | | |
| B13 | Reliability + admin | Opus | todo | | |
| B14 | Hardening + parity check | Sonnet | todo | | |
| SEC | Strix security test of the full backend | Opus | todo | | Needs Docker image + Strix LLM key |

## Track 2 — Frontend (after Track 1 + SEC)

Phases are defined by the orchestrator when Track 2 starts. Opus builder only.

## Track 3 — Wiring and launch

See `docs/WIRING_CHECKLIST.md`.

## Prerequisites before B0

- [x] Write access on `eax0106/axon` (account havishvardhan04-creator)
- [x] Repo stays public (owner, 2026-10-24)
- [x] Project folder created: `~/Desktop/Projects/axon-voice-engine`
- [x] Docs, rules and hooks in place
