# Gates: B8 Bulk campaigns

OWNS: services/api/app/**, services/api/migrations/**, services/api/tests/**, services/engine/**, services/worker/**, docs/phases/b8.md, docs/phases/b8-gates.md, docs/PARITY.md, docs/DECISIONS.md, docs/PLAN.md

Scope: Bulk campaigns to Outpero parity: contacts by CSV, paste, manual entry and saved lists with an explicit column mapping; calling window held to 9 AM to 9 PM with weekdays and holiday dates; concurrency 1 to 20; do-not-call checked at upload and before every dial; retries 0 to 9 in the same run or the next day; schedule for later and daily or weekly repeat; cross-campaign dedupe, per-campaign exclusion list and a recorded consent attestation; a live panel with its actions and CSV export; campaigns queued oldest first on a shared number with a capacity preview and analytics; the dialer and the B7 carry-over (free test calls and the code call) check for a free channel.

- [x] G0: this ledger states outcomes that can fail
  CHECK: node /mnt/project-files/skills/unlazy/scripts/gate-lint.mjs .unlazy/axon/gates/b8.md
  EXPECT: LINT OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=98ab404fea5051716c178c0d8a980e606a8e4b0747eb3bd3e0203a34bf492295; exit=0; EXPECT=matched; output-sha256=48630b7361dd44ee870917b12c3d19b9d7bdea738aaca16bb04d4cab83b772d2; output-bytes=8; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G1: locked sync, ruff check and ruff format are clean
  CHECK: uv sync --locked --all-packages && uv run ruff check . && uv run ruff format --check . && echo LINT-OK
  EXPECT: LINT-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=6c8f4e5a9125c8060557cb6680b98b7c7b8f7f8f0ae89bf64e3e3e09fe2af422; exit=0; EXPECT=matched; output-sha256=42b047baac27fd7afac8ecc65d4a6cdbbfdc6c2b8e22dfd2f579c0093557841f; output-bytes=523; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G2: mypy strict passes over every package
  CHECK: uv run mypy && echo MYPY-OK
  EXPECT: MYPY-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=bef2033e95b41573b65a65b88c63192252af802e7cd5647ce279ab440a553a8e; exit=0; EXPECT=matched; output-sha256=7ddd257978f8aee92430ba85b23c40d2569c72e6148c8339ff173a22ba8e2650; output-bytes=190; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G3: campaign settings and calling hours as pure functions of simulated time: the 9 AM to 9 PM hard limit, weekdays and holiday dates, concurrency 1 to 20, retries 0 to 9, same-run and next-day retry times, and daily or weekly repeat
  CHECK: uv run --env-file .unlazy/axon/b8-test.env pytest -p no:cacheprovider -q services/api/tests/test_campaign_settings.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=b3e1080269d0f690e6bb09713dc06e4a644f37494d2312b8f2e84d0987eec95e; exit=0; EXPECT=matched; output-sha256=1ee7ecd4b869ea57bb559cd7abee1e52d82154d2a8698d3e4e5f1f04a7c7a998; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G4: contacts by CSV, paste, manual entry and saved list: the column mapping is never guessed, bad rows are reported with their row number, values are one clean line, the do-not-call list and the exclusion list are applied at upload and a refused upload saves nothing
  CHECK: uv run --env-file .unlazy/axon/b8-test.env pytest -p no:cacheprovider -q services/api/tests/test_campaign_import.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=37e6bda395873dc9ecf7e9f9be9124fbdec04a0396bd933e3f5bb7e24d95a16c; exit=0; EXPECT=matched; output-sha256=211e31388fd556e0152665b82c873e70cd8eb3a016415f046485782e7e607861; output-bytes=237; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G5: campaign lifecycle: created only on a Bulk employee of the caller's account, the owner's consent stored word for word and required to start, start now or later, pause, resume, cancel, edit only while paused, and a plain refusal for every wrong move
  CHECK: uv run --env-file .unlazy/axon/b8-test.env pytest -p no:cacheprovider -q services/api/tests/test_campaign_lifecycle.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=9fe23f82ca95d5777e9a7eaf53010aca8580354af5221b409e3edd34193930e9; exit=0; EXPECT=matched; output-sha256=08fa7ac99271528b7862af2f37c906f2b07750efe74c71b91085334258f7bafb; output-bytes=237; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G6: the scheduler under simulated time: hours and holidays, concurrency, free channel, retries in the same run and the next day, do-not-call, dedupe across campaigns, credits, the dial rule table, unknown outcomes held, schedule for later, repeat, and oldest-first sharing of one number
  CHECK: uv run --env-file .unlazy/axon/b8-test.env pytest -p no:cacheprovider -q services/api/tests/test_campaign_dialing.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=c80a41d1ac63b4b13a4503eddaff49c325bcf2449eb843a65dbade8bb3eefa1f; exit=0; EXPECT=matched; output-sha256=5ea22cb8e3d5c28ae3565337479a209b960bb45f6b58b924e33cf37a95b9d178; output-bytes=237; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G7: live panel and its actions: counts, calling now, callbacks, retry exhausted, cancel callbacks, restore not-called, per-contact call now, cancel and retry, CSV export that cannot run a formula, all scoped to the account
  CHECK: uv run --env-file .unlazy/axon/b8-test.env pytest -p no:cacheprovider -q services/api/tests/test_campaign_panel.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=233e2ffa6b484b1fcce61ac3cc36f9b6aa32e51420a1da7c538521d4fc86c169; exit=0; EXPECT=matched; output-sha256=d96f451f18a507621092c994777db2724200c940a9890291d692f5a51084c0c4; output-bytes=237; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G8: analytics and capacity preview: answer rate, outcomes, spend, calls by day, remaining time and cost, and the older campaigns ahead on the same number
  CHECK: uv run --env-file .unlazy/axon/b8-test.env pytest -p no:cacheprovider -q services/api/tests/test_campaign_analytics.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=4dec36436a6b583b15309a6f63088f7b96a210359e0ceb74fe3002f95b2cb3b3; exit=0; EXPECT=matched; output-sha256=36e8e0e166b740a3e38ca3ac3a35f2435678a78525cc2da05a187442f1a7b09e; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G9: a callback asked for during a campaign call moves that contact to a callback at the asked time inside the calling hours, and the campaign call carries its contact's variables into the script
  CHECK: uv run --env-file .unlazy/axon/b8-test.env pytest -p no:cacheprovider -q services/api/tests/test_campaign_hooks.py services/engine/engine_tests/test_campaign_plan.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=e80f1825834d65906fe28d869b4514173294b476cc10100867a07cfca6905fc8; exit=0; EXPECT=matched; output-sha256=219d60ada291b5e584b8111bb1ccd73854b4e23dd107569d22674a1aad5e9f47; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G10: B7 carry-over: a free phone test call and the owner-phone code call refuse while every channel of the number is on a call, and a test call holds a channel once it is answered
  CHECK: uv run --env-file .unlazy/axon/b8-test.env pytest -p no:cacheprovider -q services/api/tests/test_free_channel.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=debcf152fdb49d1affb6d006ec645d2beac4d9ed0ced5f79d389c63f1778bac9; exit=0; EXPECT=matched; output-sha256=6d573669e36a7b2bbfa75c22d3ced5ceda58177a5a81c4ac6d41b59db58c2df2; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G11: migrations apply on an empty database, match the models, and downgrade to nothing
  CHECK: uv run --env-file .unlazy/axon/b8-test.env pytest -p no:cacheprovider -q services/api/tests/test_migrations.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=0d1cfbac7f6540b4b439428064902fc01bcea2b6cb2aad6b3892b09a7219f175; exit=0; EXPECT=matched; output-sha256=368c6c1163d34149be7125b48bd98a20718baac801f86b12b54b84aca98529cc; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G12: the worker runs the campaign tick every few seconds
  CHECK: uv run --env-file .unlazy/axon/b8-test.env pytest -p no:cacheprovider -q services/api/tests/test_worker.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=a38fd7bfa0deab6998ed29c51a9a3d3284b74ba417921563cbc03402dbef867d; exit=0; EXPECT=matched; output-sha256=1545ad4cea3d3794fd406673d928f84b79e0e36c884b1b4874621bfe4ec9949b; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G13: full suite passes against real Postgres and Redis and nothing is skipped except requires_keys tests
  CHECK: uv run --env-file .unlazy/axon/b8-test.env pytest -q -p no:cacheprovider -rs | grep -E "^(SKIPPED|FAILED|ERROR)|passed" | grep -v requires_keys
  EXPECT: /^\d+ passed, \d+ skipped[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=10b494d283d1e48cf2f67d2aee9124f6bd41452bfb0109fef422c8e95de1e5ea; exit=0; EXPECT=matched; output-sha256=ac0ec7ce6a751d3da4ef3a89a416a02d2e3888243750bf58a0f3963376874c19; output-bytes=194; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G14: the CI compose job on the PR head passes (it starts the stack, migrates to the new head and prints COMPOSE HEALTHY); this sandbox has no Docker daemon, so CI is the authority
  CHECK: gh api repos/eax0106/axon/commits/phase/b8-bulk-campaigns/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\" and (.name | test(\"compose\"))) | .name] | join(\",\")"
  EXPECT: compose
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=f15f9e9093c2a3ede4febb18e2f2d1cefdbd660dec4da064d61c2368a1c9f91a; exit=0; EXPECT=matched; output-sha256=ef2f853e994eb62355038198e16dbbcf9298e508fab4885373d87cf891ddde7e; output-bytes=24; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G15: CI on the PR head passes the test jobs on ubuntu, macos and windows
  CHECK: gh api repos/eax0106/axon/commits/phase/b8-bulk-campaigns/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\") | .name] | join(\",\")"
  EXPECT: /^(?=.*ubuntu)(?=.*macos)(?=.*windows)/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=b1e270e1ee9cbd31c31815f4b6b634df6c95819d3bd622cea6b2d52973685c04; exit=0; EXPECT=matched; output-sha256=2f3367cf1a7bcb48ef11d041bba6ba9cfcfab55b1433e7f731b237cf2f7bf236; output-bytes=90; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G16: docs/phases/b8.md exists with a Gate results section
  CHECK: node -e "const fs=require('fs');const t=fs.readFileSync('docs/phases/b8.md','utf8');if(!t.includes('Gate results'))process.exit(1);console.log('B8-DOC-OK')"
  EXPECT: B8-DOC-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=8975ac38e557e9643dbe4f87aa8f8474e760059fedeceb08f9b9562379ce808f; exit=0; EXPECT=matched; output-sha256=06beda8eb8d4e1f2cdc17c971d56f17c4d64c4ca14262ff51b5e827f365b73b7; output-bytes=10; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G17: a callback asked for on the last call re-opens the finished campaign (and waits for the next run in a repeating one), a start time without a time zone is refused with 422, contacts added after consent need consent again, a repeating campaign keeps holding an unknown-outcome contact, a paste names the variables left empty, and resuming a campaign that was waiting for its start time keeps it waiting
  CHECK: uv run --env-file .unlazy/axon/b8-test.env pytest -p no:cacheprovider -q services/api/tests -k "reopens_the_finished_campaign or waits_for_its_next_run or without_a_time_zone or need_the_consent_again or nobody_can_account_for or script_variables_it_left_empty or keeps_waiting"
  EXPECT: /(^|\n)8 passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=b97672e004fc906c03c3525cac5b0bb8ec95557aa756f4666792d8bafa758031; exit=0; EXPECT=matched; output-sha256=10820ec14f353890460151cd536fc0bb48b3b789d7f226cb898d2092ddbefd94; output-bytes=251; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries
