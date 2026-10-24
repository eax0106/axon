# Skills catalog — software development (backend + frontend)

Scanned on 2026-10-24 from `~/.claude/skills`, `~/.claude/commands`, installed plugins and built-in Claude Code skills. Only skills relevant to building this product are listed. "Origin" comes from git remotes, license/author lines, or the plugin registry. "No marker" means no source was found on disk, so it's probably your own.

## A. Your custom skills (no third-party source found)

| Skill | What it does | Useful for |
|---|---|---|
| `research-prog` | Sourced, tagged research with memory | Vendor APIs, compliance, unknowns |
| `research-visualize` | Turns research into a visual paper page | Reports to you |
| `cavestack` | Combines caveman (terse chat) and ponytail (lean working) | Session style |
| `layaroute` | Tiered delegation to save usage | Cost control |
| `mce-index` / `mce-map` / `mce-query` | Memory Code Engine: indexes code, maps it, finds callers, callees and blast radius | Code navigation in a big repo |
| `me-index` / `me-recall` / `me-save` | Memory Engine: saves and recalls session context | Handover between sessions |
| `thermo-nuclear-code-quality-review` | Very strict maintainability review | Reviewer, big phases |

## B. Third-party skills

### Completion and process
| Skill | Origin | What it does |
|---|---|---|
| `unlazy` | git: github.com/Leonxlnx/unlazy | Gate ledgers (GATES.md), re-verification, optional Stop hook |
| `ponytail`, `ponytail-audit`, `ponytail-debt`, `ponytail-gain` | ponytail plugin 4.8.4 | Lean-work mode, audits, debt tracking |
| `caveman`, `caveman-commit`, `caveman-review` | caveman plugin | Terse chat, terse commits, one-line reviews |
| OMC commands: `autopilot`, `ralph`, `ralplan`, `ultrawork`, `ultraqa`, `team`, `plan`, `deep-interview`, `trace`, `debug`, `visual-verdict`, `learner`, `remember`, `wiki`, `deepinit` | oh-my-claudecode command bundle (`~/.claude/commands`) | Autonomous loops, planning, QA cycles, tracing, project wiki |
| `spec-workflow:*` (`quick-spec`, `spec-elicitation`, `parallel-tasks`) | command bundle | Specs before code |

### Engineering principles and coding (pstack family, alongside ponytail)
| Skill | What it does |
|---|---|
| `pstack-architect` | Sketches types, signatures and modules before code |
| `pstack-blast-radius` | Finds what a change could break outside the diff |
| `pstack-tdd` | Test-first workflow (only when asked) |
| `pstack-typescript-best-practices` | Rules for every .ts / .tsx file |
| `pstack-technical-writing` | Docs standard (Diátaxis, Google style) |
| `pstack-correct` | Turns repeated agent mistakes into structural guards |
| `pstack-figure-it-out` | Playbook for big, novel tasks |
| `pstack-benchmark-checklist` | Vets performance measurements (latency work) |
| `pstack-unslop` | Removes AI tells from writing |
| `pstack-principle-*` (about 22) | Apply automatically: fix root causes, prove it works, model the domain, idempotent operations, type discipline, test behaviour not implementation, boundary discipline, and more |

### Review and quality
| Skill | Origin | What it does |
|---|---|---|
| `open-code-review` / `open-code-review-delegate` | Alibaba, Apache-2.0 | Rule-based code review |
| `improve` | shadcn, MIT | Senior-advisor survey with prioritised fixes |
| `improve-codebase-architecture` | terminal-skills, Apache-2.0 | Architecture improvement plan |
| `strix` | Apache-2.0 | Security testing |
| command bundles `dev:*`, `test:*`, `security:*`, `performance:*`, `docs:*`, `deploy:*` | command bundle | Debug-error, write-tests, e2e-setup, security-audit, dependency-audit, performance-audit, containerize, CI setup, API docs |

### Frontend and design
| Skill | Origin | What it does |
|---|---|---|
| `impeccable` (shape, craft, audit, polish, animate, layout, typeset, colorize, harden, …) | Apache-2.0 bundle | Full UI design-engineering workflow |
| `design-motion-principles` (+ create and audit workflows) | command bundle | Motion design per Emil Kowalski, Jakub Krehel, Jhey Tompkins; audits AI-slop motion |
| `emil-design-eng` | command bundle | Design-engineering polish |
| `animate-skill`, `review-animations` | command bundle | CSS and Framer Motion animation reference and review |
| `taste-skill`, `gpt-tasteskill`, `minimalist-skill`, `brutalist-skill`, `soft-skill`, `redesign-skill`, `stitch-skill`, `output-skill` | command bundle | Visual taste and style presets |
| `image-to-code-skill`, `imagegen-frontend-web` | command bundle | Mockup to code, design reference images |
| `brandkit` | command bundle | Brand kit generation |

### Research and data
| Skill | Origin | What it does |
|---|---|---|
| `brightdata-plugin:*` (search, scrape, discover-api, …) | Bright Data plugin | Web research and API discovery |

## C. Anthropic / Claude Code official

| Skill or plugin | What it does |
|---|---|
| `code-review` (built-in) | Bug-focused review of a diff, branch or PR; `--comment` posts inline PR comments, `--fix` applies fixes |
| `simplify` (built-in) | Cleans up the changed code: reuse, simplification, efficiency |
| `security-review` (built-in) | Security review of changes |
| `verify` (built-in) | Proves a change works; run before every commit |
| `run` (built-in) | Launches and drives the app to see a change working |
| `init` (built-in) | Creates CLAUDE.md |
| `update-config` (built-in) | Hooks and permissions in settings.json |
| `fewer-permission-prompts` (built-in) | Allowlists safe read-only commands |
| `skill-creator` / `plugin-authoring` | Makes project skills and mods |
| plugin `pr-review-toolkit` | Multi-angle PR review agents (tests, types, silent failures, comments) |
| plugin `feature-dev` | Guided feature development with explorer and architect agents |
| plugin `code-simplifier` | Simplifier agent |
| plugin `commit-commands` | commit, commit-push-pr, clean branches |
| plugin `hookify` | Creates hooks from plain rules |
| plugin `security-guidance` | Security warnings while editing |
| plugin `context7` | Up-to-date library docs (Pipecat, FastAPI, React, Motion) |
| plugin `serena` | Semantic code navigation and edits |
| plugin `pyright-lsp`, `typescript-lsp` | Type-aware code intelligence |
| plugin `playwright` | Browser automation and e2e tests |
| plugin `github` | GitHub PRs and issues |
| plugin `claude-md-management` | Keeps CLAUDE.md files healthy |
| plugin `session-report` | Session usage and activity reports |
| plugin `ralph-loop` | Autonomous keep-going loop |
| plugin `frontend-design` | Frontend design guidance |
| `dataviz` (built-in) | Chart and dashboard visualization rules |
| `anthropic-skills:web-artifacts-builder`, `theme-factory`, `built-in-browser` | Artifacts, themes, browser checks |

## Overlaps — pick one of each

| Job | Candidates |
|---|---|
| Code review | built-in `code-review` · `pr-review-toolkit` · `open-code-review` · `caveman-review` · `thermo-nuclear-code-quality-review` |
| Verify before done | built-in `verify` · OMC `verify` · `pstack-principle-prove-it-works` · `unlazy` gates |
| Simplify | built-in `simplify` · plugin `code-simplifier` · `ponytail` |
| Security | built-in `security-review` · `security:security-audit` · `strix` · plugin `security-guidance` |
| Autonomous loop | `ralph` (OMC) · plugin `ralph-loop` · `autopilot` · `ultrawork` · `unlazy` Stop hook |
| Code navigation | `mce-*` · plugin `serena` · LSP plugins |
| Session memory and handover | `me-*` · repo docs · OMC `remember` / `wiki` |
| UI design workflow | `impeccable` · `taste-skill` family · plugin `frontend-design` · `emil-design-eng` |
| Motion | `design-motion-principles` · `animate-skill` · `review-animations` · `impeccable animate` |

Not relevant here (left out): the video and HyperFrames family, slideshow, laya, svelte, rust/tauri, wfgy, reasoning, semantic, boundary and simulation bundles, LSPs for other languages, messaging plugins.
