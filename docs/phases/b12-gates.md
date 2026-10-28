# Gates: B12 Developer platform

OWNS: services/api/app/**, services/api/migrations/**, services/api/tests/**, services/engine/**, services/worker/**, .env.example, docs/phases/b12.md, docs/phases/b12-gates.md, docs/PARITY.md, docs/DECISIONS.md, docs/PLAN.md, docs/WIRING_CHECKLIST.md

Scope: Developer platform to Outpero parity: API keys, a versioned public REST API with an OpenAPI spec and a Postman collection, a request log and API status, signed account webhooks for six events with a delivery log, resend, secret rotation and a test button, and a per-employee result webhook with a trigger (all connected, skip voicemail, voicemail only) behind the publish gate.

- [x] G0: this ledger states outcomes that can fail
  CHECK: node /root/unlazy/scripts/gate-lint.mjs .unlazy/axon/gates/b12.md
  EXPECT: LINT OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=d3c4c1d031381f7addebcf764f776ddd62a0c938f093985196cc07d3b3ee122e; exit=0; EXPECT=matched; output-sha256=48630b7361dd44ee870917b12c3d19b9d7bdea738aaca16bb04d4cab83b772d2; output-bytes=8; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G1: locked sync, ruff check and ruff format are clean
  CHECK: uv sync --locked --all-packages && uv run ruff check . && uv run ruff format --check . && echo LINT-OK
  EXPECT: LINT-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=6c8f4e5a9125c8060557cb6680b98b7c7b8f7f8f0ae89bf64e3e3e09fe2af422; exit=0; EXPECT=matched; output-sha256=1c4fb791e52ed620d92b3d4f18c097107ec833827e257a802effb2001f0f7c2f; output-bytes=522; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G2: mypy strict passes over every package
  CHECK: uv run mypy && echo MYPY-OK
  EXPECT: MYPY-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=bef2033e95b41573b65a65b88c63192252af802e7cd5647ce279ab440a553a8e; exit=0; EXPECT=matched; output-sha256=d85aa38cafc26a31983a2043c821b9a5b7f3d60974e116bf3153178346373e7d; output-bytes=190; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G3: API keys: a key is shown once at creation and only its hash is stored, listing never shows it, only the owner creates or revokes, the number of active keys is capped, a revoked key stops working at once, and the public API refuses a missing, malformed, unknown or revoked key with 401
  CHECK: uv run --env-file .unlazy/axon/b12-test.env pytest -p no:cacheprovider -q services/api/tests/test_dev_keys.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=43b8c29d6cb6e3f4809562456de58d6ba0c17af72327124ae8f225934c646416; exit=0; EXPECT=matched; output-sha256=274522fc3f86e77296a83968378368620c61e2d9258e85af3292dbddddebf08e; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G4: public API v1: account, employees, calls (filters, cursor, test calls hidden), leads and campaigns are readable with a key and only for that key's account, a lead posted to an Instant employee is accepted, deduplicated or rejected exactly as the website intake does, and a key over its per-minute allowance gets 429 with Retry-After
  CHECK: uv run --env-file .unlazy/axon/b12-test.env pytest -p no:cacheprovider -q services/api/tests/test_dev_public_api.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=b93e05bbe2dc656d99933e566a86ca5f684f1308a8dc6fc7b8c0df479a653301; exit=0; EXPECT=matched; output-sha256=f58e225f9b84388abfee6c463430da6cd331107af34280f205b3814c44d7f164; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G5: request log and status: every request made with a key is logged with method, path, status and duration (a 401 has no account and is not logged), the log is scoped to the account and filterable, old rows are pruned, and the status endpoint reports requests, errors and the webhook queue
  CHECK: uv run --env-file .unlazy/axon/b12-test.env pytest -p no:cacheprovider -q services/api/tests/test_dev_request_log.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=194a293537707e06c8abedb54b33a19e7816edaf1f4eba035a803c03f138d72b; exit=0; EXPECT=matched; output-sha256=fb96c1b16dd916e69fe53b374647273a3226e7e8769e2a751469e6b5b446b713; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G6: OpenAPI and Postman: the public spec is a structurally valid OpenAPI 3.1 document (unique operation ids, every $ref resolves, bearer scheme applied to every operation, no internal route leaks in) and the Postman collection v2.1 has one request for every operation
  CHECK: uv run --env-file .unlazy/axon/b12-test.env pytest -p no:cacheprovider -q services/api/tests/test_dev_openapi.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=81f561a8d8ea0e9e46077c67c517ca2a9b44db3bab724a82c53c5956728b2242; exit=0; EXPECT=matched; output-sha256=71a52bb85b614e7168eeaff52fff9ddb5b254e01aa6be08eda87746dbe99a044; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G7: account webhooks: create, list, edit, disable and delete endpoints; the address must be https on the standard port with no login; events must be among the six; the signing secret is shown only on creation and rotation; rotating changes the signature of the next delivery; only the owner changes them; another account's endpoint is a 404
  CHECK: uv run --env-file .unlazy/axon/b12-test.env pytest -p no:cacheprovider -q services/api/tests/test_dev_webhooks_api.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=f9af6d975b01034d66f3113e97dc13565825f127417f6825c0ed989ffe9f7991; exit=0; EXPECT=matched; output-sha256=b893a7f6fa3ef7e7cdd38209a186972aff506edc8ba5436a16d390c50cb21593; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G8: signing and delivery: the signature (HMAC-SHA256 over timestamp.body) verifies with the documented scheme, a failed delivery is retried on the ladder and ends failed after the last attempt, redirects are not followed, an address inside a network is refused and recorded as failed, a crashed claim is retried, and a removed or disabled endpoint is never called
  CHECK: uv run --env-file .unlazy/axon/b12-test.env pytest -p no:cacheprovider -q services/api/tests/test_dev_delivery.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=b2538e0e342b365a03fd14ffb1f726238a764902edeb6f99cb3cecb5dc4441cf; exit=0; EXPECT=matched; output-sha256=187e6877b26b231b0f4a4ff21b43d8fc52738511fb8bed32f28e34cdf911732b; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G9: delivery log, resend and test: deliveries list with filters and show the exact payload, a resend makes a new delivery of the same event, a pending delivery cannot be resent, and a test event is sent at once and answers the receiver's status
  CHECK: uv run --env-file .unlazy/axon/b12-test.env pytest -p no:cacheprovider -q services/api/tests/test_dev_deliveries_api.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=7b74bce48f05f47905c8569536d23660c980ebc00a431ef9dbd240bb34780027; exit=0; EXPECT=matched; output-sha256=787763732e9c87492380d7a0b197b484ce34dceb38e9a6905585ae7c1902f2e1; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G10: call events: call.completed, call.not_connected, call.inbound_answered and call.inbound_missed are each announced exactly once per real call when it has settled (an answered call waits for its analysis), never for test calls or calls that never dialed, with the documented payload, and the scan reads a partial index that leaves out test and cancelled calls
  CHECK: uv run --env-file .unlazy/axon/b12-test.env pytest -p no:cacheprovider -q services/api/tests/test_dev_call_events.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=4503eca15be2fb785a101ebdcb46b97e312351b7a8f41a22ad1ef9f143abfd55; exit=0; EXPECT=matched; output-sha256=794978e5066232700c0dc4ee092db554b7fd241071b09bb672c2fc8158d3607c; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G11: lead.created fires once for a new lead from intake, from an unknown caller and from a bulk campaign's first dial (not for an existing lead), and campaign.status_changed fires for every status change on every path (start, schedule, pause, resume, cancel, the worker starting or completing a campaign) with the old and new status
  CHECK: uv run --env-file .unlazy/axon/b12-test.env pytest -p no:cacheprovider -q services/api/tests/test_dev_entity_events.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=8ba03263946f2e919ca8f2e02e5674d8fb2c31b9caa198884978a90798899b62; exit=0; EXPECT=matched; output-sha256=c448c8179ef4fe85c25be7ad33187603aedfe3464ddb4bd3f98709938ebf6fcd; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G12: fan-out: an event becomes a delivery for every active endpoint of the same account that subscribed to its type and for nobody else, nothing is made for an account with no endpoint, and an event is fanned out once
  CHECK: uv run --env-file .unlazy/axon/b12-test.env pytest -p no:cacheprovider -q services/api/tests/test_dev_fanout.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=90bb777f243ead4943f2a9d49d98cc161698e7be8c44b44d306ef4781928c51c; exit=0; EXPECT=matched; output-sha256=44c0bd9920b0d406bb32a2f71488b48971a1a5e628227ae67125f12adb01d87f; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G13: voicemail: the analysis marks a call as voicemail only when the caller's own recorded words are quoted from the transcript, the flag is stored on the call and is false when the analysis was skipped or failed
  CHECK: uv run --env-file .unlazy/axon/b12-test.env pytest -p no:cacheprovider -q services/api/tests/test_voicemail.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=37e213455e7cbed89314fb78162e64f34c2ac019bf5e0fed33c621feb0a7460d; exit=0; EXPECT=matched; output-sha256=cdabc919b5a911771f8b57fd36ad5163060b7df587d3f70f4267eb120673425a; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G14: per-employee result webhook: it lives in the script bundle behind the publish gate (a draft edit does not reach calls), the trigger picks all connected calls, skips voicemail or sends voicemail only, a call that did not connect sends nothing, the secret is masked on every read and kept while the host is unchanged, an edit that does not mention it leaves it alone, the test payload is delivered at once, and a resend goes to the hook as published now (and is refused when it was removed)
  CHECK: uv run --env-file .unlazy/axon/b12-test.env pytest -p no:cacheprovider -q services/api/tests/test_result_webhook.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=40651e5a7f968901c752ecd0b7778d4bd92c44908d06665cfdec1f2774a45d74; exit=0; EXPECT=matched; output-sha256=d84b075c3a334d862161d04ad01c4a7a9cbfffa3dda9355493e604636fbdfaf9; output-bytes=237; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G15: migration 0010 applies on an empty database, matches the models, downgrades to nothing, and calls that already existed are not announced when it is applied
  CHECK: uv run --env-file .unlazy/axon/b12-test.env pytest -p no:cacheprovider -q services/api/tests/test_dev_migration.py services/api/tests/test_migrations.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=51af568606c323fe6e257c22d40604a7d6a8509e2711d6e4c7e30b5da607b2bf; exit=0; EXPECT=matched; output-sha256=be04408ac4ca75434b0246b90bf6b1df0630c88ba1c70d099238ae4acb2c0692; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G16: the worker runs a webhook tick every few seconds that announces settled calls, fans events out and delivers what is due, and an hourly clean-up that prunes old log rows and events; the tick sends a settled call once and nothing twice
  CHECK: uv run --env-file .unlazy/axon/b12-test.env pytest -p no:cacheprovider -q services/api/tests/test_dev_worker.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=2fff44801a1845b8d0a736c456cc8febd067030f154edb8016881657e3bcab31; exit=0; EXPECT=matched; output-sha256=2bac69769430c370d9784d60d865f76019b6ea930205c36803bb923beb16854c; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G17: the engine, worker and API suites together pass against real Postgres and Redis and nothing is skipped except requires_keys tests
  CHECK: uv run --env-file .unlazy/axon/b12-test.env pytest -q -p no:cacheprovider -rs | grep -E "^(SKIPPED|FAILED|ERROR)|passed|failed" | grep -v requires_keys
  EXPECT: /^(?![\s\S]*(SKIPPED|FAILED|ERROR|failed))[\s\S]*\d+ passed/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=40ab8b72793c8a0473dce309ae8497031871075fce67ec6a3acf603935ebfee8; exit=0; EXPECT=matched; output-sha256=50b3323edd8626839f8effb3e4c610fa75ffc9368b6cda4dec1e6d66376119dd; output-bytes=195; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G18: the CI compose job on the PR head passes (it starts the stack, migrates to the new head and prints COMPOSE HEALTHY); this sandbox has no Docker daemon, so CI is the authority
  CHECK: gh api repos/eax0106/axon/commits/phase/b12-developer-platform/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\" and (.name | test(\"compose\"))) | .name] | join(\",\")"
  EXPECT: compose
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=99b73cf6da8e20d2dd33dc6d0c73a1b3a301208de09f54a3c558ebb5f61ec836; exit=0; EXPECT=matched; output-sha256=ef2f853e994eb62355038198e16dbbcf9298e508fab4885373d87cf891ddde7e; output-bytes=24; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G19: CI on the PR head passes the test jobs on ubuntu, macos and windows
  CHECK: gh api repos/eax0106/axon/commits/phase/b12-developer-platform/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\") | .name] | join(\",\")"
  EXPECT: /^(?=.*ubuntu)(?=.*macos)(?=.*windows)/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=3b19e79a2f6a6549cdce2e8dc066a0e66a327c2911ce1c92b5c3606e2f960d53; exit=0; EXPECT=matched; output-sha256=a035c7c2c03c5b46325f2c1a6d20afba791c48822b359a075d04f948a6016261; output-bytes=90; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G20: docs/phases/b12.md exists with a Gate results section
  CHECK: node -e "const fs=require('fs');const t=fs.readFileSync('docs/phases/b12.md','utf8');if(!t.includes('Gate results'))process.exit(1);console.log('B12-DOC-OK')"
  EXPECT: B12-DOC-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=fc43d97e1188e1884677fccbeacfbb3bf84d98094dfddfda91bacdf52e2de04d; exit=0; EXPECT=matched; output-sha256=9311800407213d0aec24773a84b3364a1eff5b977f169c1c3c7dc5840abceb7a; output-bytes=11; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries
