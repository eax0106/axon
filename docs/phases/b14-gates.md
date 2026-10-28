# Gates: B14 Hardening and parity check

OWNS: services/api/app/**, services/api/tests/**, scripts/**, deploy/**, .env.example, docs/runbooks/**, docs/phases/b14.md, docs/phases/b14-gates.md, docs/phases/b14-parity-audit.md, docs/phases/b14-security-review.md, docs/phases/SUMMARY.md, docs/PARITY.md, docs/DECISIONS.md, docs/PLAN.md, docs/WIRING_CHECKLIST.md

Scope: Backend hardening and the parity check: sign-up, sign-in and password-change attempts are rate limited, password hashing no longer blocks the server, a request body over 10 MB is refused, the owner can record accepting the terms of service; a sweep proves every route refuses an anonymous caller (except a listed, reasoned set) and every admin route refuses a non-admin; backups can be taken and restored into a fresh database; a load test script measures the API and reports latency and errors; every PARITY.md row is mapped to routes and tests that exist and no backend row is left unticked; runbooks cover deploy, backup and restore, incidents, capacity and secret rotation; a security review is written and its findings fixed or handed to the owner; and docs/phases/SUMMARY.md covers B0 to B14.

- [x] G0: this ledger states outcomes that can fail
  CHECK: node /root/unlazy/scripts/gate-lint.mjs .unlazy/axon/gates/b14.md
  EXPECT: LINT OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=c1536bdad254db470f35c5f508c6f43765ae5a5f51bf3440feb6714aedf51830; exit=0; EXPECT=matched; output-sha256=48630b7361dd44ee870917b12c3d19b9d7bdea738aaca16bb04d4cab83b772d2; output-bytes=8; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G1: locked sync, ruff check and ruff format are clean
  CHECK: uv sync --locked --all-packages && uv run ruff check . && uv run ruff format --check . && echo LINT-OK
  EXPECT: LINT-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=6c8f4e5a9125c8060557cb6680b98b7c7b8f7f8f0ae89bf64e3e3e09fe2af422; exit=0; EXPECT=matched; output-sha256=0bef3e605518fbd8a2b82d982f81c80374a96178a08d60f0f0e3affb50a107e1; output-bytes=520; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G2: mypy strict passes over every package, scripts included
  CHECK: uv run mypy && echo MYPY-OK
  EXPECT: MYPY-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=bef2033e95b41573b65a65b88c63192252af802e7cd5647ce279ab440a553a8e; exit=0; EXPECT=matched; output-sha256=a873ca40f20905268113c0255f533c5762a5d8668585eff17105e6fd7a7d4d70; output-bytes=190; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G3: sign-in, sign-up and password-change rate limits: the 11th wrong password for one email in the window is refused with 429 and a Retry-After header (a correct password is refused too while locked, so the lock leaks nothing about the account), an unknown email is limited the same way, one address cannot create more than 10 accounts an hour, a different email or address is unaffected, a successful sign-in clears that email's count, a wrong current password on password change is limited, and with Redis down the attempt is still answered; 30 parallel wrong guesses get exactly 10 attempts; a slow password check does not hold up another request
  CHECK: uv run --env-file .unlazy/axon/b14-test.env pytest -p no:cacheprovider -q services/api/tests/test_auth_rate_limit.py services/api/tests/test_auth.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=d4c9b5ff1f0237a9d2eb711778ff07249e2c023733651d4d617b95d49b95e99b; exit=0; EXPECT=matched; output-sha256=9a0cd545c262eebd33f2b8a5f07df2ed02f1a12be70accfa8cc49911bfefb1bf; output-bytes=237; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G4: route sweep over every operation in the OpenAPI spec: an anonymous caller gets 401 or 403 everywhere except a listed set of public routes, each with its reason and each still existing, and a signed-in non-admin gets 403 on every /admin route
  CHECK: uv run --env-file .unlazy/axon/b14-test.env pytest -p no:cacheprovider -q services/api/tests/test_route_security.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=5ac0a87bdb82d09348c5022f7076f0354f4da45897b040ba74e2ca6149d914f5; exit=0; EXPECT=matched; output-sha256=703f7857bbfee10a749197e9887b9ce7a37b076fa77d4073cc37d47f35389681; output-bytes=762; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G5: backup and restore: a dump of a database with data restores into a new empty database with the same rows in every table, restoring into a database that already has tables is refused, and old dumps beyond the keep count are removed
  CHECK: uv run --env-file .unlazy/axon/b14-test.env pytest -p no:cacheprovider -q services/api/tests/test_backup.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=4b0d6df0e81b79e1dd88cae31846a12569e1e911c30d1f1c511d2c36c8228867; exit=0; EXPECT=matched; output-sha256=fe36f874350041ef5749423adfae15dec23d7b538b1be72ab608f1335b2ffe62; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G6: the load test script drives signup, sign-in and the read routes of many simulated users at once against the API and reports p50, p95 and p99 latency per route and the error count, exits non-zero on any error or when p95 is above the limit given, and says plainly when the rate limit refused it
  CHECK: uv run --env-file .unlazy/axon/b14-test.env pytest -p no:cacheprovider -q services/api/tests/test_load_script.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=cc0c16d6b7c1f0e067b5e9040fdd95501f1327f6f0c5956c874b60dbb6d4f7f6; exit=0; EXPECT=matched; output-sha256=abeffe456dfcb1722f74b7cbc84dbf81f9c32a4a175998a85b1537387a2e3992; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G7: the parity audit: PARITY.md has no unticked row above its "Outside the backend" section, every row is mapped in the audit file, and every METHOD path the audit names exists in the app and every test file it names exists
  CHECK: uv run --env-file .unlazy/axon/b14-test.env pytest -p no:cacheprovider -q services/api/tests/test_parity_audit.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=a05c83f569dab875eb99c9bb47c9b7cefe4245ff4e8244ac1931b97fa2045e05; exit=0; EXPECT=matched; output-sha256=c08bc26732c4eeab88bff6ccb59b078ce3529924205272607c07d962347f3801; output-bytes=755; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G8: runbooks exist for deploy, backup and restore, incidents, capacity and secret rotation; every AXON_ setting they name is in .env.example or read by the code, and every script they name exists
  CHECK: uv run --env-file .unlazy/axon/b14-test.env pytest -p no:cacheprovider -q services/api/tests/test_runbooks.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=fd699fde170447278e2b868fcb78e8d39576b57afb70fc0849c1f745e293288c; exit=0; EXPECT=matched; output-sha256=428954dc348bdb004156c4b03a885b2dcb350aac6d654839104929a874d3dd06; output-bytes=757; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G9: every finding of the security review is marked fixed, accepted with a reason, or handed to the owner, and none is left open
  CHECK: node -e "const t=require('fs').readFileSync('docs/phases/b14-security-review.md','utf8');const rows=t.split('\n').filter(l=>/^\| F\d+ /.test(l));if(rows.length<5)process.exit(1);const open=rows.filter(l=>!/\| (fixed|accepted|owner) \|/.test(l));if(open.length)process.exit(2);console.log('REVIEW-CLOSED '+rows.length)"
  EXPECT: /REVIEW-CLOSED \d+/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=3b18e9a1b484bce4d2a35a59d444fd17b3f9508503cea2a0edf2e96e39f58aa1; exit=0; EXPECT=matched; output-sha256=04ab7394e6061967236777f731fff352d61d0f0e30423c4602d76558cdd27014; output-bytes=17; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G10: the engine, worker and API suites together pass against real Postgres and Redis and nothing is skipped except requires_keys tests
  CHECK: uv run --env-file .unlazy/axon/b14-test.env pytest -q -p no:cacheprovider -rs | grep -E "^(SKIPPED|FAILED|ERROR)|passed|failed" | grep -v requires_keys
  EXPECT: /^(?![\s\S]*(SKIPPED|FAILED|ERROR|failed))[\s\S]*\d+ passed/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=81ab2166b6b1a5b0dce338101754914a823fe6277c06578ff76558669fc501c6; exit=0; EXPECT=matched; output-sha256=6792cce8a7302820af87df7a6c7ea6f6d8f6f937fc61649b372a6e3521a38659; output-bytes=195; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G11: the CI compose job on the PR head passes (it starts the stack, migrates and prints COMPOSE HEALTHY); this sandbox has no Docker daemon, so CI is the authority
  CHECK: gh api repos/eax0106/axon/commits/phase/b14-hardening-parity/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\" and (.name | test(\"compose\"))) | .name] | join(\",\")"
  EXPECT: compose
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=b49514fc38612c92e7499e01a031d87d4675ea467e25d3901516c601d1059d28; exit=0; EXPECT=matched; output-sha256=ef2f853e994eb62355038198e16dbbcf9298e508fab4885373d87cf891ddde7e; output-bytes=24; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [ ] G12: CI on the PR head passes the test jobs on ubuntu, macos and windows
  CHECK: gh api repos/eax0106/axon/commits/phase/b14-hardening-parity/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\") | .name] | join(\",\")"
  EXPECT: /^(?=.*ubuntu)(?=.*macos)(?=.*windows)/
  CWD: ../../..
  EVIDENCE: pending

- [x] G13: docs/phases/b14.md has a Gate results section and docs/phases/SUMMARY.md covers B0 to B14
  CHECK: node -e "const fs=require('fs');const a=fs.readFileSync('docs/phases/b14.md','utf8');const s=fs.readFileSync('docs/phases/SUMMARY.md','utf8');if(!a.includes('Gate results'))process.exit(1);for(let i=0;i<=14;i++){if(!new RegExp('\\\\bB'+i+'\\\\b').test(s))process.exit(2)}console.log('B14-DOCS-OK')"
  EXPECT: B14-DOCS-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=e509abf698232cd5465ceab81319376f29fb0212d7858079b164877dd73555e9; exit=0; EXPECT=matched; output-sha256=703bfb246f9db3d26a54beeef87a8026516367644b522504c6de7bc4631fda33; output-bytes=12; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G14: a request body over 10 MB is refused with 413 whether its size is announced or sent in chunks, and a body just under the limit reaches the route
  CHECK: uv run --env-file .unlazy/axon/b14-test.env pytest -p no:cacheprovider -q services/api/tests/test_body_limit.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=7c0c65ca19c819412ee9b7ec30a0370fb9283e9fb313e7b172fb2daacda901fd; exit=0; EXPECT=matched; output-sha256=9e90755398ba391ac25fcfa7bab3b5029a57f672f1b651b7de087e73b87e00bf; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G15: the owner records accepting a version of the terms (readable by members, never by a member or a support session, kept in the audit log), and migration 0012 applies, matches the models and downgrades
  CHECK: uv run --env-file .unlazy/axon/b14-test.env pytest -p no:cacheprovider -q services/api/tests/test_account_terms.py services/api/tests/test_migrations.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=17f2b80ef9d01aa46385e7512762e56690c39b00aa8e3dd93420888f63fab845; exit=0; EXPECT=matched; output-sha256=fd1361b69068c8902ec74ca534b57b92a49f70274c3a2a9eba7d7e4ee404087f; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries
