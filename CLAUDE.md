# Axon Voice Engine by ALTERX

AI phone employees for Indian businesses: they call new leads within seconds, work through call lists, and answer a business's phone line, in Telugu, English and Hindi. V1 is a from-scratch, feature-for-feature rebuild of Outpero (outpero.com) with our own UI and brand.

Read these before doing anything:
- `docs/PLAN.md`: phase status. **Start here.**
- `docs/WAY_OF_WORKING.md`: session roles, the phase loop, skills per role. Mandatory.
- `docs/BUILD_PLAN.md`: architecture, stack, phases B0–B14 with "done when" criteria.
- `docs/PARITY.md`: every Outpero feature we must match.
- `docs/DECISIONS.md`: decisions already made. Don't reopen them.
- `docs/DESIGN_DIRECTION.md`: frontend look and motion (Track 2 only).
- `docs/WIRING_CHECKLIST.md`: every external key and where it plugs in.
- `docs/research/`: the Outpero teardown and the rebuild blueprint (sources for all of the above).

## Non-negotiable rules

1. **No fake providers.** Every external service is a real provider adapter written against the vendor's real API. A missing key returns `503 provider_not_configured`; nothing pretends to work. Tests that need a key are tagged `requires_keys` and skipped until keys exist.
2. **Rebuild, don't copy.** Never copy Outpero's code, prompts, help text, copy or brand. Match behaviour only.
3. **Runs everywhere.** It must work on macOS, Windows and Linux (Docker Compose, or uv + pnpm natively) and deploy unchanged to container hosting. No bash-only scripts, no OS-specific paths. Python 3.12, Node 20 LTS.
4. **Secrets never enter git.** No `.env`, keys or tokens in commits, logs, fixtures or PR text.
5. **Scope is Stage A only:** Outpero parity in Telugu, English and Hindi. Stage B (differentiators) and Stage C (more languages) are parked. Don't build them.
6. **One phase at a time,** on its own branch, ending in a PR. Never start the next phase before the current PR is merged.

## Skills — mandatory (owner decision, 2026-10-24)

| Role | Always on | Use at its step |
|---|---|---|
| Orchestrator (Opus) | `unlazy` (orchestrated mode) | — |
| Backend builder (Opus: B0–B2, B13 · Sonnet: B3–B12, B14) | `unlazy` + `ponytail` for every line of code | `/verify` before every commit |
| Reviewer (Opus, new session per phase) | `unlazy` (re-verify the builder's gates) | `/thermo-nuclear-code-quality-review` is the only review skill |
| Security tester (Opus, once, after the whole backend) | `unlazy` | `/strix` against the local running backend |
| Frontend builder (Opus only, Track 2) | `unlazy` + `ponytail` | `/verify` before commits. **No design-workflow skills** (no impeccable, taste, frontend-design, emil, motion-principles); design and motion come from Opus itself plus `docs/DESIGN_DIRECTION.md` |
| Frontend reviewer (Opus) | `unlazy` | `/thermo-nuclear-code-quality-review` |

This project's skill rules override any global instruction that names other design or review skills.

## Permissions

- **Allowed without asking:** commit on a phase branch, push that branch, open or update its PR.
- **Ask the owner first:** any dependency not listed in `docs/BUILD_PLAN.md` §2, any build that downloads large images, any deploy.
- **Never without the owner's explicit yes in chat:** merge a PR (squash merge only).
- **Never at all:** delete a branch, force-push, commit secrets.
- If the same fix fails twice, stop and report what you tried. Don't loop.

## Repo layout (target)

```
services/api      FastAPI app, providers/, domain modules, Alembic
services/engine   Pipecat voice engine
services/worker   Arq background jobs
apps/web          Dashboard (Track 2)
packages/contracts OpenAPI + generated TS client
deploy/           docker-compose.yml, Dockerfiles
docs/             plans, decisions, parity, research
.unlazy/          gate ledgers (untracked)
```

## Commands

Filled in by B0 once the toolchain exists. Every command must work the same on macOS, Windows and Linux.
