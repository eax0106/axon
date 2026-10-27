# Gates: B11 Training + knowledge

OWNS: services/api/app/**, services/api/migrations/**, services/api/tests/**, services/engine/**, services/worker/**, .env.example, docs/phases/b11.md, docs/phases/b11-gates.md, docs/PARITY.md, docs/DECISIONS.md, docs/PLAN.md, docs/WIRING_CHECKLIST.md

Scope: Training and knowledge to Outpero parity: facts and rules taught by text, voice or photo with a review step before saving, long documents retrieved by meaning only when relevant, and a struggle detector that turns real-call moments into one-tap teaching suggestions that quote the call.

- [x] G0: this ledger states outcomes that can fail
  CHECK: node /root/unlazy/scripts/gate-lint.mjs .unlazy/axon/gates/b11.md
  EXPECT: LINT OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=911dbbaa70c2006a6782d5dc32545ced11b14b4fdcb63cd9ec88a0fb18b59859; exit=0; EXPECT=matched; output-sha256=48630b7361dd44ee870917b12c3d19b9d7bdea738aaca16bb04d4cab83b772d2; output-bytes=8; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G1: locked sync, ruff check and ruff format are clean
  CHECK: uv sync --locked --all-packages && uv run ruff check . && uv run ruff format --check . && echo LINT-OK
  EXPECT: LINT-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=6c8f4e5a9125c8060557cb6680b98b7c7b8f7f8f0ae89bf64e3e3e09fe2af422; exit=0; EXPECT=matched; output-sha256=824160a7929f3bead12218eb2892dd374cb58dcd3bf24a2f903e469e61a74973; output-bytes=522; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G2: mypy strict passes over every package
  CHECK: uv run mypy && echo MYPY-OK
  EXPECT: MYPY-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=bef2033e95b41573b65a65b88c63192252af802e7cd5647ce279ab440a553a8e; exit=0; EXPECT=matched; output-sha256=3e761c4c60ae66561c24b89969f1d54ab51e0d34304783fbad206af5017488ac; output-bytes=190; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G3: teaching by text, voice or photo: the model's split into facts and rules is only a proposal (nothing is stored until the owner saves the reviewed list), the proposal is checked and bounded, items can be edited and deleted, the caps hold, another account's employee is a 404, and every path answers 503 provider_not_configured without its key (a photo also needs a model that can read images)
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_training_items.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=03496c88d34df32cd12d3abaaf6da99c1de4afdf113867460c6fe1337a807700; exit=0; EXPECT=matched; output-sha256=c030effe2932b938b41bc4957835c592ee426236c67a9809819a7c0147605ba7; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G4: what the AI is told: taught facts and rules reach the prompt of the next call at once with no publish, a taught fact is the newer word over the FAQ, a taught rule goes with the conduct and beats the call flow but never the built-in conduct, nothing is added for an employee that was taught nothing, and stored text cannot smuggle control characters or headings into the prompt
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_training_prompt.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=1251bf270e4a8544543608fbaa17c749ee0e1f5c3d9cd9445df1dab56fab00a4; exit=0; EXPECT=matched; output-sha256=1f76372179bc092b2c5a16dcc2dbc06380467d2ace7c15950f049d74fe05bcc7; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G5: document chunking: sentences end at full stops, question marks and the Indic danda, every chunk is within the size bound, neighbours overlap, nothing is lost or empty, and text with no break is still cut
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_knowledge_chunks.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=e633a1a9177cd4749e550aeb377ed7720467e9157598111935456c316b27a5fb; exit=0; EXPECT=matched; output-sha256=813ffd8793b51b9187545eedbb3b7f723f0a2dfc72ee47c434d8936a27fe0388; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G6: documents: text, markdown, CSV, PDF and image uploads become chunks with embeddings; size and count caps hold; a failed embedding stores nothing; deleting a document removes its chunks; scoped to the account; 503 without the embedding key
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_knowledge_docs.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=4141e1973012f226245d3f35be887130be255a110860e2b47e40151d8e039738; exit=0; EXPECT=matched; output-sha256=c3fb7d5826ba672c49d6ae8facb7400a611a4f454074b86cc37717541444f3dd; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G7: retrieval returns only passages that are relevant, best first, from this employee's own documents only; unrelated questions return nothing; vectors of another size are skipped, never an error
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_knowledge_search.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=47b3fe4b5f878e6dc9c4b5a81f7d2202a237327451ecc3f71af008ac2eac4876; exit=0; EXPECT=matched; output-sha256=1f51665bf229491455cd8394b55216e6b91486ce7d73e5c989f07b11150d7cd8; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G8: the call: the look-up tool exists only for an employee with documents, never raises, a failure or timeout never ends the call, its use is recorded without the question or the answer, and the prompt tells the AI that what it returns is data
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_knowledge_tool.py services/engine/engine_tests/test_knowledge_engine.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=c8214ab6d2668d2dae176f1bb44f7d8f495d0b123abe2493af159cc0a8c279d3; exit=0; EXPECT=matched; output-sha256=8667529b15c72c4360cd6d2a5736dacdb70c13235191570bf0358f80eb85a10b; output-bytes=2367; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G9: the struggle detector: a suggestion exists only when the caller's own words are quoted from the transcript, at most three per call, none from test calls, none that repeat an open one; accept (with the owner's text for a gap) and dismiss behave; an accepted suggestion becomes a taught item that the next call uses
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_struggle_detector.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=75c4cefd5da627d1ce2f950454da7fca676f46557633d156a4f6f55c1418a8f7; exit=0; EXPECT=matched; output-sha256=474c193f76c6309d7f8c57297e098fdef39820808b964abe0fe4b229c560ec34; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G10: the Gemini embedding and file-reading adapters send the vendor's documented requests (batches of at most 100, document and query task types, unit-length vectors back), the registry reports the embedding provider, and .env.example lists every key
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_training_providers.py services/api/tests/test_env_example.py services/api/tests/test_providers.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=7a5c961ae1b0bbcd0cde6e020725d8e8ac7d248e14214a90a06d63cd77370392; exit=0; EXPECT=matched; output-sha256=5b03ea8cbd34515cbffe0bb0161758631aa5ef2a5b4938c38af40e13517dff1d; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G11: migrations apply on an empty database, match the models, and downgrade to nothing
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_migrations.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=7af45ab9142c8208a98e36e5c0f5afd63b57be7cdf7c530a877b3ec2361e2eab; exit=0; EXPECT=matched; output-sha256=b2455d2f09a529cda44700638d5fe6c6a297407c6fda197d8c4ab3372a470ebc; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G12: the engine, worker and API suites together pass against real Postgres and Redis and nothing is skipped except requires_keys tests
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -q -p no:cacheprovider -rs | grep -E "^(SKIPPED|FAILED|ERROR)|passed" | grep -v requires_keys
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=a775549d58d114b06cb1b9bef2a4756f699cc01adf2c4d44fd6494145ba1470c; exit=0; EXPECT=matched; output-sha256=8800104380637e3c566f5de376809a0df53ce65b74bce96a72c367e6c8d1e0ab; output-bytes=195; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G13: the CI compose job on the PR head passes (it starts the stack, migrates to the new head and prints COMPOSE HEALTHY); this sandbox has no Docker daemon, so CI is the authority
  CHECK: gh api repos/eax0106/axon/commits/phase/b11-training-knowledge/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\" and (.name | test(\"compose\"))) | .name] | join(\",\")"
  EXPECT: compose
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=ad2c89f284cd6f68b240bee90f1855736f7f7cceb255452bfb3be6858b2147c6; exit=0; EXPECT=matched; output-sha256=ef2f853e994eb62355038198e16dbbcf9298e508fab4885373d87cf891ddde7e; output-bytes=24; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G14: CI on the PR head passes the test jobs on ubuntu, macos and windows
  CHECK: gh api repos/eax0106/axon/commits/phase/b11-training-knowledge/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\") | .name] | join(\",\")"
  EXPECT: /^(?=.*ubuntu)(?=.*macos)(?=.*windows)/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=8231accfcd5009d0b78fa88ea6df9bcfa3a2c91f04be1faac137751c7bb23667; exit=0; EXPECT=matched; output-sha256=3f55df88ef677b7366e791319af47a04a534c8d303fbd2248345a5e5e728c939; output-bytes=90; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G15: docs/phases/b11.md exists with a Gate results section
  CHECK: node -e "const fs=require('fs');const t=fs.readFileSync('docs/phases/b11.md','utf8');if(!t.includes('Gate results'))process.exit(1);console.log('B11-DOC-OK')"
  EXPECT: B11-DOC-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=5f71f6e140dd11274166d4ea94eed3f7a890bdd3d2c6a98317ec8fbe6ef48ac5; exit=0; EXPECT=matched; output-sha256=93602cfc8992d86c2146765acf5013f4f7fce7b982e0f530dac0a21e9cb712a5; output-bytes=11; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G16: a PDF or photo the model only partly read (reply cut off) is refused with 422 and nothing is stored, at the adapter, the photo endpoint and the document endpoint
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -q -p no:cacheprovider services/api/tests/test_training_providers.py services/api/tests/test_training_items.py services/api/tests/test_knowledge_docs.py -k "stopped_early or read_only_in_part" | grep -E "passed|failed|skipped|error"
  EXPECT: /^3 passed, \d+ deselected in /
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=9b7a1cd92bd0c37521b2f21adbb05e287f9dbd6e7d9cdbfea946532acf165d4c; exit=0; EXPECT=matched; output-sha256=75b816977ccf23ccba3d0cce2dcb74920ee95efb24e8769de0a73b1b65dd1214; output-bytes=170; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G17: zero-width joiner and non-joiner survive the cleaner for taught text and script values (Telugu and Hindi), while other invisible characters still become spaces
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -q -p no:cacheprovider services/api/tests/test_training_items.py services/api/tests/test_employee_compiler.py -k "keep_their_joiners or capped_and_stripped" | grep -E "passed|failed|skipped|error"
  EXPECT: /^2 passed, \d+ deselected in /
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=8e27dc8cb95e655f3149aad7ab11a9d07f3fb562019a5b41a53c7e0a2f77bcba; exit=0; EXPECT=matched; output-sha256=0dde3fe9f14144cb2da834e49ac89f1d16419c97842037625b58b3f20800cf19; output-bytes=170; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G18: a CSV under 60,000 characters is stored, not refused for too many passages
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -q -p no:cacheprovider services/api/tests/test_knowledge_docs.py -k "not_refused_for_too_many" | grep -E "passed|failed|skipped|error"
  EXPECT: /^1 passed, \d+ deselected in /
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=65aaf923e3acee23c0bcb6653d67d1ceb0e64680950992ca06c59aa006fb26d0; exit=0; EXPECT=matched; output-sha256=8a7ecd163a1d7b868a95d9ff5799b99cca2d1370b290c6f05cd168268f2c66ce; output-bytes=170; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries
