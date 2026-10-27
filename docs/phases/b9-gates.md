# Gates: B9 Inbound

OWNS: services/api/app/**, services/api/migrations/**, services/api/tests/**, services/engine/**, services/worker/**, docs/phases/b9.md, docs/phases/b9-gates.md, docs/PARITY.md, docs/DECISIONS.md, docs/PLAN.md

Scope: Inbound to Outpero parity: answer on the attached number 24/7 or within opening hours (closed message, take a message), recording disclosure before the greeting, greetings for new callers and returning leads, messages and callback tasks with a done tick, missed callers with reasons and one auto call-back inside calling hours that never goes to the do-not-call list, a daily summary email, transfer to a human, Instant and Bulk employees answering their own leads' call-backs, and concurrent callers limited by the number's channels.

- [x] G0: this ledger states outcomes that can fail
  CHECK: node /root/unlazy/scripts/gate-lint.mjs .unlazy/axon/gates/b9.md
  EXPECT: LINT OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=8823b03eaa7dc66ac38d6dc4371494bc0879db5fea6d377bf2c2b812f9c90152; exit=0; EXPECT=matched; output-sha256=48630b7361dd44ee870917b12c3d19b9d7bdea738aaca16bb04d4cab83b772d2; output-bytes=8; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G1: locked sync, ruff check and ruff format are clean
  CHECK: uv sync --locked --all-packages && uv run ruff check . && uv run ruff format --check . && echo LINT-OK
  EXPECT: LINT-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=6c8f4e5a9125c8060557cb6680b98b7c7b8f7f8f0ae89bf64e3e3e09fe2af422; exit=0; EXPECT=matched; output-sha256=eb41b5776b47cbbdaa2bec839f6536d2d8ba17bacccb61eefc5bc67b3de3268b; output-bytes=520; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G2: mypy strict passes over every package
  CHECK: uv run mypy && echo MYPY-OK
  EXPECT: MYPY-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=bef2033e95b41573b65a65b88c63192252af802e7cd5647ce279ab440a553a8e; exit=0; EXPECT=matched; output-sha256=9c21101f4e2442a634ef568b0efdddc8ef43b0d2c9128b7a59f16935292b9a28; output-bytes=190; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G3: inbound settings and opening hours as pure functions of simulated time: 24/7 or weekly windows in IST, a transfer number that must be an Indian number, greetings that may not use a name for a new caller, and plain refusals for every bad value
  CHECK: uv run --env-file .unlazy/axon/b9-test.env pytest -p no:cacheprovider -q services/api/tests/test_inbound_settings.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=b67455d8e7c16066ef2a3756397a415dcdd0e1e38985b0e0b581f0a33b900746; exit=0; EXPECT=matched; output-sha256=7ddf9a5f990c1302607bf05ceeb4d324e75472d309e2b1e8070f8a415f85f144; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G4: routing a call that arrives on a number: answered when the employee is live, otherwise missed with a plain-language reason (paused, no credits or spend cap, rule table, outbound-only employee, no employee, closed with hang-up mode); closed with message-taking mode is answered as closed; the same carrier call id twice is one call row; a call the carrier does not have live is refused
  CHECK: uv run --env-file .unlazy/axon/b9-test.env pytest -p no:cacheprovider -q services/api/tests/test_inbound_routing.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=8ccdb96eec5b78b738a23bb598a7d89ced19dee2ad8574d0afce46540fd80bbc; exit=0; EXPECT=matched; output-sha256=4199ec961d4ec12991629801a152bbb42c5bfd692bdfed74a6938c4ec26dcb96; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G5: concurrent callers are limited by the number's channels: the call that finds every channel busy is missed as busy, a finished call frees its channel, and an inbound call holds a channel from the moment it is answered
  CHECK: uv run --env-file .unlazy/axon/b9-test.env pytest -p no:cacheprovider -q services/api/tests/test_inbound_channels.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=6ee3fd0ce52be8f3cdf83dda86cdff3b8cf8df540eeac63cd1f50a088f31c43a; exit=0; EXPECT=matched; output-sha256=51e62ff2b76db3ff780da8d6eae94026fe66a01803cc9850ae8d88221a7d4ac5; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G6: the recording disclosure comes before the greeting in every language, new callers and returning leads get their own greeting, the business name and caller name are filled in, the opening is never empty, and the compiled prompt carries the closed, message-taking and transfer rules only when they apply
  CHECK: uv run --env-file .unlazy/axon/b9-test.env pytest -p no:cacheprovider -q services/api/tests/test_inbound_greeting.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=4e8628285c0d1213916dcd861e31049f6be57884427b19044de3b78c387678dc; exit=0; EXPECT=matched; output-sha256=c575ddf1387664b49a697f351d13acde503e1c38c404b2013b639b571999c0cc; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G7: the Vobiz adapter creates the answer-URL application, attaches a number to it and transfers a live call with the documented requests; connecting a number is idempotent; going live as an inbound employee without telephony is refused with 503 and the employee stays as it was
  CHECK: uv run --env-file .unlazy/axon/b9-test.env pytest -p no:cacheprovider -q services/api/tests/test_inbound_vobiz.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=88cf6fdc20068d42e19d51014a451e19a45184bf4267a455c1df7534ad3f28db; exit=0; EXPECT=matched; output-sha256=e96ca9d116eaf1c925229b2181135e770b61627f06e091d3c148c17cf604dfc2; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G8: the engine answers an inbound call: the answer URL returns the stream XML for the right employee, the opening (disclosure then greeting) is spoken before the caller says anything, a missed call is rejected with a hang-up, and the stream URL stays closed to a call the carrier does not have
  CHECK: uv run --env-file .unlazy/axon/b9-test.env pytest -p no:cacheprovider -q services/engine/engine_tests/test_inbound_engine.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=9204df057eff6529a46b188033d8c23d73c848e76ae89c8f0b652fd3f4237a8b; exit=0; EXPECT=matched; output-sha256=643f48e706b63dc51e879e1ad05057ee7e60f89d7959d55bb0f50df317eeea33; output-bytes=1855; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G9: transfer to a human: the function exists only when a transfer number is set, the transfer waits for the spoken words to finish, the call is handed to the carrier without hanging up, the dial XML names the transfer number and the employee's own number as caller id, a transfer that does not connect leaves a message for the owner, and talk time after the transfer is not billed
  CHECK: uv run --env-file .unlazy/axon/b9-test.env pytest -p no:cacheprovider -q services/engine/engine_tests/test_transfer.py services/api/tests/test_inbound_billing.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=12fdc56f9939e0e824cee1674837cb4cf5c145566deea947f6310f8010a2a7a4; exit=0; EXPECT=matched; output-sha256=55e74e3b715a74744014f9b69d45c4a68f19f76f3a7247823213f1113cc98887; output-bytes=2327; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G10: messages and callback requests: taken from what the caller said (a message the caller did not say is dropped), one per call, listed per account with open, done and all views, a done tick that can be undone, scoped to the account, and a bell entry when one arrives
  CHECK: uv run --env-file .unlazy/axon/b9-test.env pytest -p no:cacheprovider -q services/api/tests/test_inbound_messages.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=0c36461b0625f41bf0dd76d4ed98b29c5c072524a85ee6f6415ec6480d16502b; exit=0; EXPECT=matched; output-sha256=784025095192b8e49281c383b84e3a616bc35825e389012f7fef07d771aa3500; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G11: missed callers are listed with plain-language reasons and the number that called, scoped to the account, and appear in conversations with the reason
  CHECK: uv run --env-file .unlazy/axon/b9-test.env pytest -p no:cacheprovider -q services/api/tests/test_inbound_missed.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=a36659c3cf8047fe955b7b3e7e98c9bb746986fade3308ee89ce799e53df0ea3; exit=0; EXPECT=matched; output-sha256=664c30b7a33937b46722d02560b0aa23674c9fc84e3560dd8b8be2775fc629b0; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G12: one auto call-back to a missed caller, inside calling hours, never to a number on the do-not-call list, never twice for the same caller in a day, dialed by the Instant dialer under the call-back rule, never retried; an inbound employee's requested callback is dialed too; an inbound call that ends unanswered is never redialed
  CHECK: uv run --env-file .unlazy/axon/b9-test.env pytest -p no:cacheprovider -q services/api/tests/test_inbound_callback.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=ad67923095670440c63f7e7691b7b8e6caa6b2f8abe6d3413f6a003368fd9c2c; exit=0; EXPECT=matched; output-sha256=ea40953c84b37d19cb30a3290a74801e876d01acee5015b2a374f925f1e9e56f; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G13: the daily summary email covers yesterday's inbound calls in India time, is sent once per account per day, only when there were calls, only for employees with the summary on, and a missing email provider sends nothing and loses nothing
  CHECK: uv run --env-file .unlazy/axon/b9-test.env pytest -p no:cacheprovider -q services/api/tests/test_inbound_summary.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=0191c8e780209fef351a46afbd5ca72bef1b58ac3cafed6fc1c2efeda547064f; exit=0; EXPECT=matched; output-sha256=5577eb45202265f8b2c5eb110b4edd383663d5d86c7e1f58a98f119c68dab88b; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G14: Instant and Bulk employees answer their own leads' call-backs when the toggle is on, with the lead's details, memory, last call and campaign row as context, and miss the call with a reason when it is off
  CHECK: uv run --env-file .unlazy/axon/b9-test.env pytest -p no:cacheprovider -q services/api/tests/test_inbound_context.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=e1aff2a7eee65eff68fb21dfe3f1c07694db654092f210497fa30d7cd14702be; exit=0; EXPECT=matched; output-sha256=64e3b6bf4a404b56557f3921e139320562fa7323d22d8185fdcfe87fabeedab9; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G15: migrations apply on an empty database, match the models, and downgrade to nothing
  CHECK: uv run --env-file .unlazy/axon/b9-test.env pytest -p no:cacheprovider -q services/api/tests/test_migrations.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=3d5be840e1a30186cbc12b70df251382d9f1e3c0462caf4c6179975c7fac950e; exit=0; EXPECT=matched; output-sha256=b2455d2f09a529cda44700638d5fe6c6a297407c6fda197d8c4ab3372a470ebc; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G16: the worker runs the daily summary tick
  CHECK: uv run --env-file .unlazy/axon/b9-test.env pytest -p no:cacheprovider -q services/api/tests/test_worker.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=346ff875c7c196dd2be7f05dbae8bb5b4a486c9e00ec3be5286500d64eceefa8; exit=0; EXPECT=matched; output-sha256=5e93df93bf27e85d534e9c02bf829c2421487ddb0de6484d01e851786b9aec08; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G17: full suite passes against real Postgres and Redis and nothing is skipped except requires_keys tests
  CHECK: uv run --env-file .unlazy/axon/b9-test.env pytest -q -p no:cacheprovider -rs | grep -E "^(SKIPPED|FAILED|ERROR)|passed" | grep -v requires_keys
  EXPECT: /^\d+ passed, \d+ skipped[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=13a82e0b32d9c0bc2d2a0f9ebcc53740d69e901eb2c0a97a4c4c3ec2a4b033c7; exit=0; EXPECT=matched; output-sha256=864f7f10e886905ae796d8bf85642818395806ce7cad31714fb4eae89af94224; output-bytes=194; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [ ] G18: the CI compose job on the PR head passes (it starts the stack, migrates to the new head and prints COMPOSE HEALTHY); this sandbox has no Docker daemon, so CI is the authority
  CHECK: gh api repos/eax0106/axon/commits/phase/b9-inbound/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\" and (.name | test(\"compose\"))) | .name] | join(\",\")"
  EXPECT: compose
  CWD: ../../..
  EVIDENCE: pending

- [ ] G19: CI on the PR head passes the test jobs on ubuntu, macos and windows
  CHECK: gh api repos/eax0106/axon/commits/phase/b9-inbound/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\") | .name] | join(\",\")"
  EXPECT: /^(?=.*ubuntu)(?=.*macos)(?=.*windows)/
  CWD: ../../..
  EVIDENCE: pending

- [x] G20: docs/phases/b9.md exists with a Gate results section
  CHECK: node -e "const fs=require('fs');const t=fs.readFileSync('docs/phases/b9.md','utf8');if(!t.includes('Gate results'))process.exit(1);console.log('B9-DOC-OK')"
  EXPECT: B9-DOC-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=7788260a619014054572605753edc62ff69d3cae653a2aa39d769f9c4daad3bd; exit=0; EXPECT=matched; output-sha256=8153a080c02c7e731f539b2fad040a17b5ac94025f09a06f6b59501e4b95c3aa; output-bytes=10; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries
