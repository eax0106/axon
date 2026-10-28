# Gates: B13 Reliability and admin

OWNS: services/api/app/**, services/api/migrations/**, services/api/tests/**, services/engine/**, services/worker/**, .env.example, docs/phases/b13.md, docs/phases/b13-gates.md, docs/PARITY.md, docs/DECISIONS.md, docs/PLAN.md, docs/WIRING_CHECKLIST.md

Scope: Reliability and admin to Outpero parity: per-leg failover mid-call (speech-to-text, LLM, text-to-speech) with health scoring, a Premium voice falling back to a Value voice at the Value price and never the other way, a spoken apology and clean hang-up when a leg has nothing left, no call started while nothing is healthy (retried later), capacity limits, the account's max call length, do-not-call list and settings (business name, password change that revokes old sessions), the admin console APIs (accounts, logged impersonation, credit adjustments, voice library, provider health, costs and balances, carrier capacity and reconcile, system health, revenue, announcements, alerts), support chat, feedback and rating, and the automatic retry of a failed post-call analysis.

- [x] G0: this ledger states outcomes that can fail
  CHECK: node /root/unlazy/scripts/gate-lint.mjs .unlazy/axon/gates/b13.md
  EXPECT: LINT OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=a55e969357dc6a3802529b78893b93c40a419624b07bbb2dfc29e1a482a61d5e; exit=0; EXPECT=matched; output-sha256=c448f3d5bb434b8ae92c450d4a2a138decbd30bcb81b054945c1e31121fa9236; output-bytes=393; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G1: locked sync, ruff check and ruff format are clean
  CHECK: uv sync --locked --all-packages && uv run ruff check . && uv run ruff format --check . && echo LINT-OK
  EXPECT: LINT-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=6c8f4e5a9125c8060557cb6680b98b7c7b8f7f8f0ae89bf64e3e3e09fe2af422; exit=0; EXPECT=matched; output-sha256=f38ff3730c67dc14bdc742d322a1565cb246460de7cc9355ef5fef65c31565e7; output-bytes=112; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G2: mypy strict passes over every package
  CHECK: uv run mypy && echo MYPY-OK
  EXPECT: MYPY-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=bef2033e95b41573b65a65b88c63192252af802e7cd5647ce279ab440a553a8e; exit=0; EXPECT=matched; output-sha256=81440eaa8b62b56a3dac5d80dc6c84f97ffce05095f36a95f758addcc19927cb; output-bytes=53; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G3: mid-call failover: real Pipecat adapters forced into error paths (an LLM answering 401, an LLM that never answers and times out, a text-to-speech and a speech-to-text websocket refused with 401) hand the leg to the next vendor during the call; the caller's lost turn is answered by the backup LLM; the switch is published as a `failover` event; usage is metered per vendor
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/engine/engine_tests/test_failover.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=491d2729cceaef067902d2d6ae6d8b8eefb2f22840e14b7f4089e41098910308; exit=0; EXPECT=matched; output-sha256=6b5d4fa8569473ab53dfb9c726f1c81b7cd9dafc80d94b85fa4618940e202f97; output-bytes=2116; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G4: voice tiers: each tier's text-to-speech chain is built in order (Premium falls back to Value then Standard; Value and Standard never fall back to Premium), a vendor that cannot be built (missing key, missing Cartesia Telugu voice) is skipped, unhealthy vendors are tried last, and a call that fell back is billed at the cheapest tier it used, at the configured rates
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/engine/engine_tests/test_tier_fallback.py services/engine/engine_tests/test_voice_choice.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=c59768e41e3c4733d531d741c98f5f89e29663b64260eb6ccbe6788cdb768a4c; exit=0; EXPECT=matched; output-sha256=0c74f80f0cd603714c908076ef96b8ace00c7ed025c6b4fe0ad9a9f38cd4bb13; output-bytes=1735; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G5: fatal mid-call failure: through the real engine app and Vobiz stream, when a leg has no vendor left the caller hears an apology in the call's language and the carrier is asked to hang up once it was heard (reason `provider_failure`); with text-to-speech gone the call is hung up at once; an outbound attempt that ended this way is queued again along its retry ladder
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/engine/engine_tests/test_provider_failure.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=28bff3df01058c6d3f66d555ea5b96b87a4d3e19bdf95186dcf08353645570af; exit=0; EXPECT=matched; output-sha256=613e1713f9e7df8e961ae28a04dff7aa9be370fb4e5d014f4f117776c3bea768; output-bytes=2414; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G6: health scoring: a failover records a failure for the vendor left behind and a clean call records a success for each vendor that served it; a vendor with at least 3 failures making up half or more of its last 10 minutes is unhealthy, and is healthy again once those failures age out; old outcomes are pruned
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_provider_health.py services/engine/engine_tests/test_call_records.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=82dd54f3bb34fc64faf6770a711a9f3473c61c96aa2b03cce13743a807c08af8; exit=0; EXPECT=matched; output-sha256=1c428c70dae18c052c637f79f5c17775db447b303db3d8a8cfd953c3ba96c773; output-bytes=1726; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G7: nothing healthy, nothing started: an Instant call whose speech, LLM or voice leg has no healthy configured vendor is rescheduled without dialing or using an attempt, a campaign waits with a plain note, an incoming call is missed with a reason; the platform's concurrent-call cap holds new calls; carrier failures (5xx, timeouts, rejected login) make the dialers hold while a refusal of one call does not
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_dial_readiness.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=9b3a8779589c7358dfc69b64537773abbe21e9aabafcbda777a66f60147fdcc1; exit=0; EXPECT=matched; output-sha256=ad7b11cc00be2746d328d70f2e0e1e3fb7b760c01bbb8f2f477b59718ef7887f; output-bytes=100; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G8: account settings: name, business name and max call length (10 s to 60 min, default 10 min) are read by members and changed only by the owner, and the length reaches the call plan; a password change needs the current password, signs out every older session and returns a working token; an impersonation session cannot change the password, make an API key, reveal or rotate the lead-intake secret, add or repoint a webhook, set an employee's result webhook or actions (by their own routes or the script), connect Google, or change the incoming-call transfer number
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_account_settings.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=9110b9784b050da81dda81ca4e1306ed497d3f98c854895980ef2c211d7f8e85; exit=0; EXPECT=matched; output-sha256=de2a4b89a04d1bdd9bbabcab989b13435df88fb951ef615c60798890bb1b760c; output-bytes=98; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G9: do-not-call list: add one number with a reason (normalised, idempotent), add many at once with counts of added, already listed and invalid, search and page the list, only the owner removes an entry, adding cancels queued calls to that number, and everything is scoped to the account
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_dnc_api.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=bbf790cfeb88dfb4a14fee0722b96ab63e3ed4dc027310145632a2b773fbe87b; exit=0; EXPECT=matched; output-sha256=377084747a6cb3df5c20c215b1d01f0cd9c6a199d67be32a1c358417335304c3; output-bytes=98; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G10: admin accounts: every admin route refuses a non-admin with 403; accounts list, search and detail; impersonation needs a reason, is written to the audit log, acts as the account owner for 30 minutes, logs every change made under it with the staff member's id, cannot reach admin routes and stops when the staff member loses admin rights; a credit adjustment posts to the ledger with an audit row and cannot take the balance below zero
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_admin_accounts.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=3e4f97de8e724eb09389b0f94dfc83dbb410e780bca4ce031d30dc32f90faed1; exit=0; EXPECT=matched; output-sha256=386b4fe02502bde80182db15c7e8be56954b00c6050700a11998a38440d4c6a7; output-bytes=638; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G11: admin operations: the voice library is created, edited and deleted (a voice in use or a duplicate is refused); provider health shows the probe and the live score; provider costs are the metered usage times the rates staff entered, with usage shown and cost left empty where no rate exists; a provider balance is the recorded balance minus the cost since it was recorded; carrier capacity shows channels and calls in flight, and a purchase in `reconcile` can be settled as kept or refunded once, and a refund whose charge cannot be found is refused and changes nothing
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_admin_ops.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=172338c8c260a8756543ff44808c1ad39c671a8062161b0aa7d30e843ededcba; exit=0; EXPECT=matched; output-sha256=ac4473271723394019d51e8454cdbf3ec4ae158c02ed1ae959d891f41d83cce0; output-bytes=98; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G12: admin reports: system health reports the database, Redis, the worker's last heartbeat and the work queues; revenue per day splits top-ups from what calls, numbers and AI help used, with provider cost and margin; an announcement reaches every account's notification bell; alerts list unhealthy providers, low provider balances, numbers waiting for reconcile and a silent worker
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_admin_reports.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=490723e7d1d6c6541a5f0653081a3ec344ed295eead9843b5523875c62ed121e; exit=0; EXPECT=matched; output-sha256=afe3d849547a92fe27144a14708f20550b245b713a522625c8a012777d2cda4e; output-bytes=98; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G13: support: a message a user writes in the support chat is answered by staff and the answer is shown in that account's thread only; feedback is stored; a rating must be 1 to 5 and name one of the account's own calls; staff see all of it in one inbox
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_support.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=bd2cd5f6d997baf822bd4d4ac8b3db4d1e8718a5824cc693b3d306a7162346d0; exit=0; EXPECT=matched; output-sha256=c7331c069370861d5353e74abe2e688eda9273fa03a4b5cb5e9fa85983f926d0; output-bytes=98; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G14: post-call analysis retry: a failed analysis is retried twice with back-off (2 then 10 minutes) and then left failed; a call is not retried before its time; re-analysis starts the count again
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_analysis_retry.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=1662b4f6c7d4bca6a81e0d13d5270f2e4eafc66253e074652eb95e38442f7020; exit=0; EXPECT=matched; output-sha256=0c778a468dab85c2738fd304e850546781d3de3a988b6bbf20e4a3edfee949d6; output-bytes=98; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G15: migration 0011 applies on an empty database, matches the models and downgrades to nothing
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -p no:cacheprovider -q services/api/tests/test_migrations.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=8fba83cc1296d9952d82932cb0f93fadfa26d87f10341e699f7e5574033d289d; exit=0; EXPECT=matched; output-sha256=c8044af9b1bbe15c1cb0d6764bb625bb4356e7985950372c0252d20a412ba543; output-bytes=98; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G16: the engine, worker and API suites together pass against real Postgres and Redis and nothing is skipped except requires_keys tests
  CHECK: uv run --env-file .unlazy/axon/b13-test.env pytest -q -p no:cacheprovider -rs | grep -E "^(SKIPPED|FAILED|ERROR)|passed|failed" | grep -v requires_keys
  EXPECT: /^(?![\s\S]*(SKIPPED|FAILED|ERROR|failed))[\s\S]*\d+ passed/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=3b4502c43f3d5f8bf606a9a93922567e7a54fc860a3c6f4124fd807146302d7d; exit=0; EXPECT=matched; output-sha256=5f327925d535a8d9a85dcc6bed75e961ab826f80781e1b7b0cc9802fc2e8e997; output-bytes=58; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G17: the CI compose job on the PR head passes (it starts the stack, migrates to the new head and prints COMPOSE HEALTHY); this sandbox has no Docker daemon, so CI is the authority
  CHECK: gh api repos/eax0106/axon/commits/phase/b13-reliability-admin/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\" and (.name | test(\"compose\"))) | .name] | join(\",\")"
  EXPECT: compose
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=0a63c8f1bee962cfde3dd8042c42e5f8660330c1a36a7caf930edc2e0837fb46; exit=0; EXPECT=matched; output-sha256=ef2f853e994eb62355038198e16dbbcf9298e508fab4885373d87cf891ddde7e; output-bytes=24; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G18: CI on the PR head passes the test jobs on ubuntu, macos and windows
  CHECK: gh api repos/eax0106/axon/commits/phase/b13-reliability-admin/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\") | .name] | join(\",\")"
  EXPECT: /^(?=.*ubuntu)(?=.*macos)(?=.*windows)/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=34c196ea69f2ce47e8633f0e3f51971c1ed10169d29fccbd6ae7a45e1a352415; exit=0; EXPECT=matched; output-sha256=57daa205644f91fbf2b777772432f9a97503c2c5ab16e8d76a62e39777448b5e; output-bytes=90; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G19: docs/phases/b13.md exists with a Gate results section
  CHECK: node -e "const fs=require('fs');const t=fs.readFileSync('docs/phases/b13.md','utf8');if(!t.includes('Gate results'))process.exit(1);console.log('B13-DOC-OK')"
  EXPECT: B13-DOC-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=783a8a26ec23d68c31c13411f7b605bd196422e6f545f93614b44e066341aeec; exit=0; EXPECT=matched; output-sha256=a3740238469d5b4a1b4d9c4bff650ad18dd3a5a0d4adb8d29a49123a355ececa; output-bytes=11; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries
