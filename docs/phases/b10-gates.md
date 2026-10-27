# Gates: B10 In-call actions

OWNS: services/api/app/**, services/api/migrations/**, services/api/tests/**, services/engine/**, services/worker/**, docs/phases/b10.md, docs/phases/b10-gates.md, docs/PARITY.md, docs/DECISIONS.md, docs/PLAN.md, docs/WIRING_CHECKLIST.md

Scope: In-call actions to Outpero parity, all opt-in per employee: a tool framework, a custom HTTP API tool with a test console, Google Calendar availability and booking with a test booking, Google Sheets read and write, and WhatsApp template messages to the person on the call; edits go through the publish gate and nothing a caller says can reach another host, another calendar or another phone number.

- [x] G0: this ledger states outcomes that can fail
  CHECK: node /root/unlazy/scripts/gate-lint.mjs .unlazy/axon/gates/b10.md
  EXPECT: LINT OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=b364fd1062d38c1eccf52fab38869fd8ba9764a8114e007258f0bbac459d36ad; exit=0; EXPECT=matched; output-sha256=48630b7361dd44ee870917b12c3d19b9d7bdea738aaca16bb04d4cab83b772d2; output-bytes=8; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G1: locked sync, ruff check and ruff format are clean
  CHECK: uv sync --locked --all-packages && uv run ruff check . && uv run ruff format --check . && echo LINT-OK
  EXPECT: LINT-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=6c8f4e5a9125c8060557cb6680b98b7c7b8f7f8f0ae89bf64e3e3e09fe2af422; exit=0; EXPECT=matched; output-sha256=83cef820b0e4e3daf61435ba7b22c5b8ef5b59fbc8c3a0faf3eddbe1ef469742; output-bytes=520; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G2: mypy strict passes over every package
  CHECK: uv run mypy && echo MYPY-OK
  EXPECT: MYPY-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=bef2033e95b41573b65a65b88c63192252af802e7cd5647ce279ab440a553a8e; exit=0; EXPECT=matched; output-sha256=7fff89aea65f0f8cd45c9b41389f9141b3f63af3b909e0a472c01f43c082b36d; output-bytes=190; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G3: the action schema: opt-in per employee (none by default), bounded counts, tool names unique and never an engine tool, https-only URLs, no credentials in a URL, no header injection, placeholders only after the host, and secrets masked on every read and kept when the mask is sent back
  CHECK: uv run --env-file .unlazy/axon/b10-test.env pytest -p no:cacheprovider -q services/api/tests/test_actions_schema.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=c6444e2a16fce4ef18baf850f8f9c231e2f494defbc8164cb55445471577e2f1; exit=0; EXPECT=matched; output-sha256=bca4f1571b281293cfa9129ead78e6f6eb4aa57233d3360a49fedf9eee33a4af; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G4: the network guard refuses loopback, private, link-local and metadata addresses, other schemes and ports, resolves once and pins the connection to the address it checked, so a name that later points inside is not followed
  CHECK: uv run --env-file .unlazy/axon/b10-test.env pytest -p no:cacheprovider -q services/api/tests/test_actions_net.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=88f249cf64d6022d05d507d25246be268d9e20c6402ada99e42449ca803b8c33; exit=0; EXPECT=matched; output-sha256=c46d9dedae6d8f37358e92eb59ca23c1b4f2218115168fdb8d21edf8413e8b0c; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G5: the custom HTTP tool against a real local server: path and query values are URL-encoded and cannot change the host, the body is JSON for POST, the secret goes out as the configured header, a redirect is not followed, an oversized or slow answer is cut short, and an error status comes back as a plain failure the AI can speak about
  CHECK: uv run --env-file .unlazy/axon/b10-test.env pytest -p no:cacheprovider -q services/api/tests/test_actions_http.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=b59ff234302b94056d7316c5a05d9cb8aadf1cc82a01ae3a140aaf8232390b73; exit=0; EXPECT=matched; output-sha256=6cadedbdae8e13cf7fe485d2d6f67ce7b5c120323a3b6a1e566689feed6706f6; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G6: the Google connection: consent URL carries the chosen scopes and a signed state bound to the user and account, connect stores the grant and the scopes Google actually gave, status shows what is connected, disconnect revokes the token at Google and removes it, 503 until the OAuth client is set, owner only
  CHECK: uv run --env-file .unlazy/axon/b10-test.env pytest -p no:cacheprovider -q services/api/tests/test_google_connection.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=4ceeed1cb04c914391a472f46afe6fa645764ac14c6c14a673b6825908aa3ccb; exit=0; EXPECT=matched; output-sha256=be601f3fd67525cc824f62064ac9ebf872db4fe1336efe9e8a923ca82513e142; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G7: Google Calendar booking: availability lists only free slots inside working days and hours, after the minimum notice and within the booking window, in fixed IST; a booking must be one of those slots and is checked against busy time again right before it is made, is idempotent for one call and time, and a busy or out-of-hours time is refused with a plain reason; the test booking creates then removes its event
  CHECK: uv run --env-file .unlazy/axon/b10-test.env pytest -p no:cacheprovider -q services/api/tests/test_actions_calendar.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=3bcb42318081415cfd6472791c89c4c93d7ad0dd3ee880a120e280945e88d6cb; exit=0; EXPECT=matched; output-sha256=e96ca9d116eaf1c925229b2181135e770b61627f06e091d3c148c17cf604dfc2; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G8: Google Sheets actions: read returns the header and only matching rows up to the limit, write appends one row in the configured column order with the call time and caller number, values are stored as text and never as formulas
  CHECK: uv run --env-file .unlazy/axon/b10-test.env pytest -p no:cacheprovider -q services/api/tests/test_actions_sheets.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=ded10d0b7d36f6bb7c3f9a5126eabf9d98672b400d51e5bfb47eee6dca074ecc; exit=0; EXPECT=matched; output-sha256=76328066d7f63c09e0f6b041eb71db48946460d2e511ecdbd0e34d8e1ad0918d; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G9: WhatsApp: Interakt and AiSensy requests match the vendors' documented shapes, the message goes only to the person on this call and only as an approved template, a call with no number sends nothing, and the test message goes only to the owner's verified phone
  CHECK: uv run --env-file .unlazy/axon/b10-test.env pytest -p no:cacheprovider -q services/api/tests/test_actions_whatsapp.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=7fdd1e7d8578a1fa4781f45adac11f93e7d4ac014a2a6a926f7acc343fc91169; exit=0; EXPECT=matched; output-sha256=a68ddf30a7cbd223443b6640ffa51f90a9be20b9e1e58c2b517a943a4845e280; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G10: actions API: edits are draft until publish (pending edits, versions, restore and revert carry them), secrets never appear in any response, Google-backed actions refuse an account that has not connected the service, the test console runs the real action, is account-scoped and rate-limited
  CHECK: uv run --env-file .unlazy/axon/b10-test.env pytest -p no:cacheprovider -q services/api/tests/test_actions_api.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=b96f4a676509a3a268510a276858b8f0f2fb6b4704d81ac3a17f70f423d6eca1; exit=0; EXPECT=matched; output-sha256=8f77b4375435ed9068154a83fbf872a99c055bf002c398122299ce65bd983d01; output-bytes=237; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G11: the compiled prompt tells the AI to treat tool results as data, to say plainly when a tool fails, and to confirm before it books; none of it appears for an employee without actions
  CHECK: uv run --env-file .unlazy/axon/b10-test.env pytest -p no:cacheprovider -q services/api/tests/test_actions_prompt.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=a470fadd48d0c6ad6cf7b79e4c4dca7e4464bdccaab07296fec9c90ffad6ded9; exit=0; EXPECT=matched; output-sha256=d6ebab855c959bfc42e8aec5ef725e2c61f7769886f13f97f065fb3172212719; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G12: the engine registers one tool per action, an action runs without being cancelled by an interruption, its result goes back to the AI, a failure or timeout never ends the call, and each use is recorded on the call without its arguments or answer
  CHECK: uv run --env-file .unlazy/axon/b10-test.env pytest -p no:cacheprovider -q services/engine/engine_tests/test_actions_engine.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=91f9dfbfe0621a383aad4d7d12663dbdbcf171485fffb3883a46dbd9a491faba; exit=0; EXPECT=matched; output-sha256=c07d930647d59c5f52e11f0bdc2fc34ed906dcf67f45d3fbdcf3ee8fd8a8a1d1; output-bytes=2155; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G13: the Google Calendar, Sheets write and WhatsApp adapters are registered with the keys they need and answer 503 provider_not_configured without them
  CHECK: uv run --env-file .unlazy/axon/b10-test.env pytest -p no:cacheprovider -q services/api/tests/test_actions_providers.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=40ac9f0df75f7f4fdc1ae69a7a9528fb6a532bc8a479b6614d33d785697e61af; exit=0; EXPECT=matched; output-sha256=8e403e1411cf799ac8bf8806d65081a587a6bd2c1341953bbb1405486df18115; output-bytes=246; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G14: migrations apply on an empty database, match the models, and downgrade to nothing
  CHECK: uv run --env-file .unlazy/axon/b10-test.env pytest -p no:cacheprovider -q services/api/tests/test_migrations.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=a3c7334324f8479a0d7f61b8f89ac0d915d499aba9d6f900f7aaa2e0a725558b; exit=0; EXPECT=matched; output-sha256=1f715b6801fa2aacc86da4febca857d002f7419d7425e74bc4e1c3f1cf222b59; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G15: the worker and API suites together pass against real Postgres and Redis and nothing is skipped except requires_keys tests
  CHECK: uv run --env-file .unlazy/axon/b10-test.env pytest -q -p no:cacheprovider -rs | grep -E "^(SKIPPED|FAILED|ERROR)|passed" | grep -v requires_keys
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=7d7232dc025b6baa08c1416c777fa0756d446cb07df1d364cfe425e89588209b; exit=0; EXPECT=matched; output-sha256=55358d0954c1439b2c00472756d3e5628fb525c49d336bc765e86f736985391f; output-bytes=194; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [ ] G16: the CI compose job on the PR head passes (it starts the stack, migrates to the new head and prints COMPOSE HEALTHY); this sandbox has no Docker daemon, so CI is the authority
  CHECK: gh api repos/eax0106/axon/commits/phase/b10-in-call-actions/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\" and (.name | test(\"compose\"))) | .name] | join(\",\")"
  EXPECT: compose
  CWD: ../../..
  EVIDENCE: pending

- [ ] G17: CI on the PR head passes the test jobs on ubuntu, macos and windows
  CHECK: gh api repos/eax0106/axon/commits/phase/b10-in-call-actions/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\") | .name] | join(\",\")"
  EXPECT: /^(?=.*ubuntu)(?=.*macos)(?=.*windows)/
  CWD: ../../..
  EVIDENCE: pending

- [x] G18: docs/phases/b10.md exists with a Gate results section
  CHECK: node -e "const fs=require('fs');const t=fs.readFileSync('docs/phases/b10.md','utf8');if(!t.includes('Gate results'))process.exit(1);console.log('B10-DOC-OK')"
  EXPECT: B10-DOC-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=48e09b41f93e5db6bd43f33dd28ba20d202a469af9dda125e2811096ac77f28d; exit=0; EXPECT=matched; output-sha256=5f2abfc1310137b73f466e290a16d10d26fe4d40d8187008cc609dee974d78de; output-bytes=11; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries
