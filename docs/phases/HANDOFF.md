# Handoff — orchestration moved to the Claude Project "axon" (2026-10-27)

Written by the lead session because the previous orchestrator stopped at a usage limit.

## State
- B0–B6 merged into `main` (see `docs/PLAN.md`).
- **B7 (billing + numbers)** is in progress on branch `phase/b7-billing-numbers`. No PR is open yet.
- The work in progress is committed as one WIP commit on that branch. It covers the billing module, the email provider, migration `0005_billing_and_numbers`, ledger, call-billing and ledger-concurrency tests, and changes to auth, post-call, limits, the dialer, models, providers, the engine and the worker.
- The B7 gate ledger (21 gates, none checked yet) is copied to `docs/phases/b7-gates.md`. Restore it into `.unlazy/axon/gates/b7.md` before continuing.

## Next
1. The new builder thread (Sonnet, high effort) checks out `phase/b7-billing-numbers` and invokes ponytail, unlazy and caveman. It reviews the WIP, finishes the remaining gates, runs /verify, opens the draft PR, and squashes the WIP commit into the phase result.
2. Then follow `docs/RUN_CHECKLIST.md` as usual through B14.

## Retired sessions (do not use)
axon-orchestrator, axon-builder-opus, axon-builder-sonnet, axon-reviewer-2. Their work is all on GitHub or on this branch.
