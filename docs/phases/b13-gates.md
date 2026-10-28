# Gates: B13 Reliability and admin

OWNS: services/api/app/**, services/api/migrations/**, services/api/tests/**, services/engine/**, services/worker/**, .env.example, docs/phases/b13.md, docs/phases/b13-gates.md, docs/PARITY.md, docs/DECISIONS.md, docs/PLAN.md, docs/WIRING_CHECKLIST.md

Scope: Reliability and admin to Outpero parity: per-leg failover mid-call (speech-to-text, LLM, text-to-speech) with health scoring, a Premium voice falling back to a Value voice at the Value price and never the other way, a spoken apology and clean hang-up when a leg has nothing left, no call started while nothing is healthy (retried later), capacity limits, the account's max call length, do-not-call list and settings (business name, password change that revokes old sessions), the admin console APIs (accounts, logged impersonation, credit adjustments, voice library, provider health, costs and balances, carrier capacity and reconcile, system health, revenue, announcements, alerts), support chat, feedback and rating, and the automatic retry of a failed post-call analysis.

- [ ] G0: this ledger states outcomes that can fail
  CHECK: node /root/unlazy/scripts/gate-lint.mjs .unlazy/axon/gates/b13.md
  EXPECT: LINT OK
  CWD: ../../..

- [ ] G1: locked sync, ruff check and ruff format are clean
  CHECK: uv sync --locked --all-packages && uv run ruff check . && uv run ruff format --check . && echo LINT-OK
  EXPECT: LINT-OK
  CWD: ../../..

- [ ] G2: mypy strict passes over every package
  CHECK: uv run mypy && echo MYPY-OK
  EXPECT: MYPY-OK
  CWD: ../../..

- [ ] G3: mid-call failover: real Pipecat adapters forced into error paths (an LLM answering 401, an LLM that never answers and times out, a text-to-speech and a speech-to-text websocket refused with 401) hand the leg to the next vendor during the call; the caller's lost turn is answered by the backup LLM; the switch is published as a `failover` event; usage is metered per vendor
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/engine/engine_tests/test_failover.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..

- [ ] G4: voice tiers: each tier's text-to-speech chain is built in order (Premium falls back to Value then Standard; Value and Standard never fall back to Premium), a vendor that cannot be built (missing key, missing Cartesia Telugu voice) is skipped, unhealthy vendors are tried last, and a call that fell back is billed at the cheapest tier it used
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/engine/engine_tests/test_tier_fallback.py services/engine/engine_tests/test_voice_choice.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..

- [ ] G5: fatal mid-call failure: through the real engine app and Vobiz stream, when a leg has no vendor left the caller hears an apology in the call's language and the carrier is asked to hang up once it was heard (reason `provider_failure`); with text-to-speech gone the call is hung up at once; an outbound attempt that ended this way is queued again along its retry ladder
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/engine/engine_tests/test_provider_failure.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..

- [ ] G6: health scoring: a failover records a failure for the vendor left behind and a clean call records a success for each vendor that served it; a vendor with at least 3 failures making up half or more of its last 10 minutes is unhealthy, and is healthy again once those failures age out; old outcomes are pruned
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_provider_health.py services/engine/engine_tests/test_call_records.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..

- [ ] G7: nothing healthy, nothing started: an Instant call whose speech, LLM or voice leg has no healthy configured vendor is rescheduled without dialing or using an attempt, a campaign waits with a plain note, an incoming call is missed with a reason; the platform's concurrent-call cap holds new calls; carrier failures (5xx, timeouts, rejected login) make the dialers hold while a refusal of one call does not
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_dial_readiness.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..

- [ ] G8: account settings: name, business name and max call length (10 s to 60 min, default 10 min) are read by members and changed only by the owner, and the length reaches the call plan; a password change needs the current password, signs out every older session and returns a working token; an impersonation session cannot change the password or make an API key
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_account_settings.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..

- [ ] G9: do-not-call list: add one number with a reason (normalised, idempotent), add many at once with counts of added, already listed and invalid, search and page the list, only the owner removes an entry, adding cancels queued calls to that number, and everything is scoped to the account
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_dnc_api.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..

- [ ] G10: admin accounts: every admin route refuses a non-admin with 403; accounts list, search and detail; impersonation needs a reason, is written to the audit log, acts as the account owner for 30 minutes, logs every change made under it with the staff member's id, cannot reach admin routes and stops when the staff member loses admin rights; a credit adjustment posts to the ledger with an audit row and cannot take the balance below zero
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_admin_accounts.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..

- [ ] G11: admin operations: the voice library is created, edited and deleted (a voice in use or a duplicate is refused); provider health shows the probe and the live score; provider costs are the metered usage times the rates staff entered, with usage shown and cost left empty where no rate exists; a provider balance is the recorded balance minus the cost since it was recorded; carrier capacity shows channels and calls in flight, and a purchase in `reconcile` can be settled as kept or refunded once
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_admin_ops.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..

- [ ] G12: admin reports: system health reports the database, Redis, the worker's last heartbeat and the work queues; revenue per day splits top-ups from what calls, numbers and AI help used, with provider cost and margin; an announcement reaches every account's notification bell; alerts list unhealthy providers, low provider balances, numbers waiting for reconcile and a silent worker
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_admin_reports.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..

- [ ] G13: support: a message a user writes in the support chat is answered by staff and the answer is shown in that account's thread only; feedback is stored; a rating must be 1 to 5 and name one of the account's own calls; staff see all of it in one inbox
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_support.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..

- [ ] G14: post-call analysis retry: a failed analysis is retried twice with back-off (2 then 10 minutes) and then left failed; a call is not retried before its time; re-analysis starts the count again
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_analysis_retry.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..

- [ ] G15: migration 0011 applies on an empty database, matches the models and downgrades to nothing
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_migrations.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..

- [ ] G16: the engine, worker and API suites together pass against real Postgres and Redis and nothing is skipped except requires_keys tests
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -q -p no:cacheprovider -rs | grep -E "^(SKIPPED|FAILED|ERROR)|passed|failed" | grep -v requires_keys
  EXPECT: /^(?![\s\S]*(SKIPPED|FAILED|ERROR|failed))[\s\S]*\d+ passed/
  CWD: ../../..

- [ ] G17: the CI compose job on the PR head passes (it starts the stack, migrates to the new head and prints COMPOSE HEALTHY); this sandbox has no Docker daemon, so CI is the authority
  CHECK: gh api repos/eax0106/axon/commits/phase/b13-reliability-admin/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\" and (.name | test(\"compose\"))) | .name] | join(\",\")"
  EXPECT: compose
  CWD: ../../..

- [ ] G18: CI on the PR head passes the test jobs on ubuntu, macos and windows
  CHECK: gh api repos/eax0106/axon/commits/phase/b13-reliability-admin/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\") | .name] | join(\",\")"
  EXPECT: /^(?=.*ubuntu)(?=.*macos)(?=.*windows)/
  CWD: ../../..

- [ ] G19: docs/phases/b13.md exists with a Gate results section
  CHECK: node -e "const fs=require('fs');const t=fs.readFileSync('docs/phases/b13.md','utf8');if(!t.includes('Gate results'))process.exit(1);console.log('B13-DOC-OK')"
  EXPECT: B13-DOC-OK
  CWD: ../../..
