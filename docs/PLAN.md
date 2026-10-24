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
| B5 | Instant channel | Sonnet | building | | |
| B6 | Post-call + data views | Sonnet | todo | | |
| B7 | Billing + numbers (incl. number types and dialer rule table) | Sonnet | todo | | |
| B8 | Bulk campaigns | Sonnet | todo | | |
| B9 | Inbound | Sonnet | todo | | |
| B10 | In-call actions | Sonnet | todo | | |
| B11 | Training + knowledge | Sonnet | todo | | |
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
