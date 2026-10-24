# Way of Working

Agreed with the owner on 2026-10-24. Every session working on this repo follows this document.

## 1. Roles

| Role | Model | Scope | Lifetime |
|---|---|---|---|
| **Orchestrator** | Opus | Starts builder and reviewer sessions, relays results, verifies claims, reports to the owner. Writes no product code. | One long-lived session |
| **Backend builder** | Opus for B0, B1, B2, B13; Sonnet (high effort) for B3–B12, B14 | Builds exactly one phase | New session per phase |
| **Reviewer** | Opus | Reviews exactly one phase PR | New session per phase |
| **Security tester** | Opus | Runs Strix once after the whole backend (after B14) | One session |
| **Frontend builder** | Opus only | Track 2 phases | New session per phase |
| **Frontend reviewer** | Opus | Reviews each frontend PR | New session per phase |

Sessions don't share chat history. **The repo is the memory:** `docs/PLAN.md`, `docs/BUILD_PLAN.md`, `docs/DECISIONS.md`, `docs/PARITY.md`, plus the phase's notes in `docs/phases/<phase>.md`.

## 2. Skills per role (mandatory)

| Role | Always on | At its step |
|---|---|---|
| Orchestrator | `unlazy` orchestrated mode: `.unlazy/axon/PLAN.md` with one leaf per phase | — |
| Backend builder | `unlazy` (write the phase GATES first) + `ponytail` (every line of code) | `/verify` before every commit |
| Reviewer | `unlazy` (`--reverify` the builder's gates) | `/thermo-nuclear-code-quality-review`, the only review skill |
| Security tester | `unlazy` | `/strix` on the running local backend (needs Docker, a ~5.8 GB image, and `STRIX_LLM` + `LLM_API_KEY`) |
| Frontend builder | `unlazy` + `ponytail` | `/verify` before commits. No design-workflow skills; follow `docs/DESIGN_DIRECTION.md` |
| Frontend reviewer | `unlazy` | `/thermo-nuclear-code-quality-review` |

How it's enforced:
- `CLAUDE.md` states the rules.
- `.claude/settings.json` enables the `ponytail` plugin for this project.
- A SessionStart hook prints `.claude/session-rules.md` into every session.
- The `unlazy` Stop hook blocks ending a turn while the active pipeline has unmet gates.

`/thermo-nuclear-code-quality-review` can't be invoked by the model on its own. The orchestrator starts every reviewer session with that slash command as the first line of its brief.

## 3. The phase loop

```
Owner (in orchestrator): "Run Bn"
  1. Orchestrator starts BUILDER (worktree, branch phase/bn-<slug>) with the phase brief.
  2. Builder:
       a. reads CLAUDE.md, docs/PLAN.md, docs/BUILD_PLAN.md §Bn, docs/PARITY.md rows for Bn
       b. writes .unlazy/axon/gates/bn.md (unlazy), lints it
       c. builds with ponytail; tests beside code
       d. runs gates until ALL MET; /verify; commits; pushes branch
       e. writes docs/phases/bn.md (what was built, decisions, how to run, gate results)
       f. opens a DRAFT PR "Bn: <title>" and stops
  3. Orchestrator checks the PR exists and CI is green, then starts the REVIEWER.
  4. Reviewer:
       a. re-verifies the builder's gates itself (unlazy --reverify)
       b. runs /thermo-nuclear-code-quality-review on the PR diff
       c. posts findings as a PR review: APPROVE or REQUEST CHANGES
  5. On changes: orchestrator sends the findings to the builder; builder fixes on the same
     branch; reviewer re-checks only those findings. Loop.
  6. On approve: reviewer marks the PR ready for review. Orchestrator reports to the owner.
  7. Owner says "merge" in chat. Squash merge. Branch kept. docs/PLAN.md updated.
  8. Next phase.
```

## 4. Order of work

1. **Track 1, backend:** B0 → B14, strictly in order.
2. **Security:** Strix on the complete backend. Fixes go through the same build and review loop.
3. **Track 2, frontend:** the dashboard on the real API (Opus builder, thermo review).
4. **Track 3, wiring:** keys from `docs/WIRING_CHECKLIST.md`, then real calls and the "keys" gates of every phase.
5. **Hosting.**

## 5. Permissions

| Action | Rule |
|---|---|
| Commit, push phase branch, open or update PR | Allowed |
| Dependency not in BUILD_PLAN §2 | Ask the owner |
| Large downloads (Docker images over 1 GB), deploys | Ask the owner |
| Merge | Only on the owner's explicit yes, squash merge |
| Delete a branch, force-push, commit secrets | Never |
| Same fix failing twice | Stop and report |

## 6. Phase brief template (orchestrator to builder)

```
Role: Backend builder for phase Bn (<title>). Model: <Opus|Sonnet>.
Repo: <path>, worktree branch phase/bn-<slug> from main.
Read first: CLAUDE.md, docs/WAY_OF_WORKING.md, docs/PLAN.md, docs/BUILD_PLAN.md §Bn, docs/PARITY.md (Bn rows), docs/DECISIONS.md.
Skills: unlazy (write .unlazy/axon/gates/bn.md first), ponytail for all code, /verify before every commit.
Done when: every gate in the ledger is met, docs/phases/bn.md written, draft PR open.
Do not: start Bn+1, merge, add unlisted dependencies, add fake providers, copy Outpero material.
Report back: PR URL, gate summary (met/unmet counts), open questions.
```

## 7. Review brief template (orchestrator to reviewer)

```
/thermo-nuclear-code-quality-review
Role: Reviewer for PR <url> (phase Bn). Model: Opus.
First: unlazy --reverify .unlazy/axon/gates/bn.md on the PR branch; report any unmet gate.
Then review the full diff against docs/BUILD_PLAN.md §Bn and docs/PARITY.md Bn rows.
Post findings as one GitHub PR review (APPROVE or REQUEST CHANGES), most severe first.
On APPROVE: mark the PR ready for review. Never merge.
Report back: verdict, finding count by severity, gate re-verification result.
```
