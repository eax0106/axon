# Run checklist — non-stop build of B0–B14

The orchestrator follows this checklist until B14 is merged. It is the single source of truth for the autonomous run.

## 1. Resources (all in this repo)

| Need | Where |
|---|---|
| Rules and skills | `CLAUDE.md`, `.claude/session-rules.md` |
| Roles, loop, brief templates | `docs/WAY_OF_WORKING.md` |
| Orchestrator duties | `docs/ORCHESTRATION.md` + this file |
| Phase scope and "done when" | `docs/BUILD_PLAN.md` §5 |
| Features to match per phase | `docs/PARITY.md` |
| Settled decisions | `docs/DECISIONS.md` |
| Status board | `docs/PLAN.md` |
| Vendor facts (Vobiz, Sarvam, Pipecat, Smart Turn, TRAI, DPDP) | `docs/research/2026-10-24-outpero-rebuild-blueprint.md` §4–6 |
| Outpero feature map (API surface, data model) | `docs/research/2026-10-24-outpero-rebuild-blueprint.md` §3 |
| Keys (none needed until Track 3) | `docs/WIRING_CHECKLIST.md` |

Local toolchain already installed on the owner's Mac: Python 3.14 (use uv to get 3.12), uv 0.11, Node 20, Docker 29, Postgres 16, Redis 8, git, gh.

## 2. Session roster

All sessions live in the sidebar group **axon**.

| Name | Model | Role | Phases |
|---|---|---|---|
| `axon-orchestrator` | Opus | Runs this checklist; writes no product code | all |
| `axon-builder-opus` | Opus | Builder (unlazy + ponytail) | B0, B1, B2, B13 |
| `axon-builder-sonnet` | Sonnet, high effort | Builder (unlazy + ponytail) | B3–B12, B14 |
| `axon-reviewer` | Opus | Reviewer (unlazy re-verify + thermo-nuclear) | every phase |

The roster is long-lived: the orchestrator sends each phase to the right builder with SendMessage instead of starting a new session per phase. That keeps the run going without needing the owner to start sessions. At the start of every phase, a builder re-reads `CLAUDE.md`, `docs/PLAN.md` and its phase section, so state comes from the repo, not from chat memory.

## 3. Per-phase checklist (orchestrator)

For each phase Bn, in order B0 … B14:

- [ ] `docs/PLAN.md` shows the previous phase `merged` (or Bn = B0)
- [ ] Builder told: phase, branch `phase/bn-<slug>` cut from latest `main`, brief from WAY_OF_WORKING §6
- [ ] Builder reports. **Verify, don't trust:** the branch exists, tests and CI are green, `unlazy --status` shows ALL MET for `.unlazy/axon/gates/bn.md`, `docs/phases/bn.md` exists
- [ ] Reviewer told: first line `/thermo-nuclear-code-quality-review`, brief from WAY_OF_WORKING §7
- [ ] Review verdict: APPROVE, or REQUEST CHANGES, which goes back to the builder; loop
- [ ] On APPROVE: merge per the merge rule in §5
- [ ] `docs/PLAN.md` row set to `merged` with PR or commit reference; unlazy dispatch state updated
- [ ] Next phase

## 4. Keeping it running

- **Heartbeat.** The orchestrator runs `/loop` (self-paced). Each tick it reads `docs/PLAN.md`, the GitHub or git state, and its notifications, then nudges whichever session should be acting. Fallback heartbeat: 20–30 minutes.
- **Usage limits.** `autoContinueAtUsageLimit` is on in `.claude/settings.json`. A session stopped by a usage limit waits for the reset and continues automatically. On every heartbeat after a reset, the orchestrator re-sends the current step to any session that is idle mid-phase.
- **Stuck rule.** If the same step fails twice, or a builder is blocked on something only the owner can provide (keys, access, a legal call), the orchestrator **records it in `docs/PLAN.md` as `blocked`, skips nothing, and tells the owner**. Every other phase waits, because phases are sequential.
- **Keys.** No phase in Track 1 needs keys. Gates that need keys are tagged `requires_keys` and are expected to be skipped.

## 5. Merge rule and pushing

Owner answers, 2026-10-24:
- **Auto-merge (standing approval, B0–B14 only):** after the reviewer APPROVEs and `unlazy --reverify` shows ALL MET, the orchestrator squash-merges the phase into `main`. Branches are never deleted. A short report per phase goes to the owner.
- **Installs and builds pre-approved:** dependencies listed in BUILD_PLAN §2 (and their normal transitive deps), local builds, tests, `docker compose up`. Anything else, or any image over 1 GB, needs the owner's yes.
- **GitHub:** use account `havishvardhan04-creator`. As of 2026-10-24 it also has READ only on `eax0106/axon`, so the run works in **local-git mode**: phase branches, reviews of local diffs, and local squash merges into `main`. The moment write access exists (`gh repo view eax0106/axon --json viewerPermission` shows WRITE, MAINTAIN or ADMIN), push `main` and all phase branches and continue with real PRs. Check this on every heartbeat.

## 6. Done

When B14 is merged: the orchestrator writes `docs/phases/SUMMARY.md` (what was built, gate totals, parity coverage, open items, the keys needed next) and reports to the owner. The SEC phase (Strix) waits for the owner's key and download approval.
