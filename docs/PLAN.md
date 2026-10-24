# Plan — status board

Owner: Havish. Orchestrator updates this file after every merge.

Legend: `todo` · `building` · `in review` · `changes` · `merged` · `blocked`

## Track 1 — Backend (in order)

| Phase | Title | Builder | Status | PR | Notes |
|---|---|---|---|---|---|
| B0 | Foundation (monorepo, Docker Compose, CI on 3 OSes, settings, provider registry) | Opus | todo | | |
| B1 | Data model + auth | Opus | todo | | |
| B2 | Voice engine (Pipecat, Vobiz serializer) | Opus | todo | | |
| B3 | Speech + LLM provider adapters | Sonnet | todo | | |
| B4 | AI employee builder | Sonnet | todo | | |
| B5 | Instant channel | Sonnet | todo | | |
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

- [ ] Owner grants Write access on `eax0106/axon` to GitHub account `havishaivardhan-svg` (currently read-only)
- [ ] Owner decides public or private repo (private recommended)
- [x] Project folder created: `~/Desktop/Projects/axon-voice-engine`
- [x] Docs, rules and hooks in place
