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
  EVIDENCE: automatic-evidence=v1; definition-sha256=6c8f4e5a9125c8060557cb6680b98b7c7b8f7f8f0ae89bf64e3e3e09fe2af422; exit=0; EXPECT=matched; output-sha256=a881ea9c86c7e39125d0e48c776d6483cd4904a191b76cbd164d19ec9263fdca; output-bytes=520; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G2: mypy strict passes over every package
  CHECK: uv run mypy && echo MYPY-OK
  EXPECT: MYPY-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=bef2033e95b41573b65a65b88c63192252af802e7cd5647ce279ab440a553a8e; exit=0; EXPECT=matched; output-sha256=3e761c4c60ae66561c24b89969f1d54ab51e0d34304783fbad206af5017488ac; output-bytes=190; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G3: teaching by text, voice or photo: the model's split into facts and rules is only a proposal (nothing is stored until the owner saves the reviewed list), the proposal is checked and bounded, items can be edited and deleted, the caps hold, another account's employee is a 404, and every path answers 503 provider_not_configured without its key (a photo also needs a model that can read images)
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_training_items.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=03496c88d34df32cd12d3abaaf6da99c1de4afdf113867460c6fe1337a807700; exit=0; EXPECT=matched; output-sha256=81259fde1ca187a8690a447b0d7ea4bd381c375e3b996fe851b7773744f41da9; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G4: what the AI is told: taught facts and rules reach the prompt of the next call at once with no publish, a taught fact is the newer word over the FAQ, a taught rule goes with the conduct and beats the call flow but never the built-in conduct, nothing is added for an employee that was taught nothing, and stored text cannot smuggle control characters or headings into the prompt
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_training_prompt.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=1251bf270e4a8544543608fbaa17c749ee0e1f5c3d9cd9445df1dab56fab00a4; exit=0; EXPECT=matched; output-sha256=4cf38b135361c62476737613e2b037c0908dcb49898f1e61e357e0acf2854438; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G5: document chunking: sentences end at full stops, question marks and the Indic danda, every chunk is within the size bound, neighbours overlap, nothing is lost or empty, and text with no break is still cut
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_knowledge_chunks.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=e633a1a9177cd4749e550aeb377ed7720467e9157598111935456c316b27a5fb; exit=0; EXPECT=matched; output-sha256=cba72df2dd4089cabbf892e575990d5f5af26f4f30f19169d190096569a25e7b; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G6: documents: text, markdown, CSV, PDF and image uploads become chunks with embeddings; size and count caps hold; a failed embedding stores nothing; deleting a document removes its chunks; scoped to the account; 503 without the embedding key
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_knowledge_docs.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=4141e1973012f226245d3f35be887130be255a110860e2b47e40151d8e039738; exit=0; EXPECT=matched; output-sha256=3ba605d67e37f6b51b8ce82ddd8cde192774a75eb759373bd29d8fba4880be99; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G7: retrieval returns only passages that are relevant, best first, from this employee's own documents only; unrelated questions return nothing; vectors of another size are skipped, never an error
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_knowledge_search.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=47b3fe4b5f878e6dc9c4b5a81f7d2202a237327451ecc3f71af008ac2eac4876; exit=0; EXPECT=matched; output-sha256=f72488960564c3f3eb6ff151e2ba4819c026401cf2d213b485589cb2b22a53e2; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G8: the call: the look-up tool exists only for an employee with documents, never raises, a failure or timeout never ends the call, its use is recorded without the question or the answer, and the prompt tells the AI that what it returns is data
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_knowledge_tool.py services/engine/engine_tests/test_knowledge_engine.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=c8214ab6d2668d2dae176f1bb44f7d8f495d0b123abe2493af159cc0a8c279d3; exit=0; EXPECT=matched; output-sha256=7e6fe0636f9ab4036c8ff1c092fe969964d47f180263b25e868967fc51d7a5c2; output-bytes=2367; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G9: the struggle detector: a suggestion exists only when the caller's own words are quoted from the transcript, at most three per call, none from test calls, none that repeat an open one; accept (with the owner's text for a gap) and dismiss behave; an accepted suggestion becomes a taught item that the next call uses
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_struggle_detector.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=75c4cefd5da627d1ce2f950454da7fca676f46557633d156a4f6f55c1418a8f7; exit=0; EXPECT=matched; output-sha256=e5f44e2a48750f5d542bc101e0e666db7a6ba531e363eeebf1c050b952f9f665; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G10: the Gemini embedding and file-reading adapters send the vendor's documented requests (batches of at most 100, document and query task types, unit-length vectors back), the registry reports the embedding provider, and .env.example lists every key
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_training_providers.py services/api/tests/test_env_example.py services/api/tests/test_providers.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=7a5c961ae1b0bbcd0cde6e020725d8e8ac7d248e14214a90a06d63cd77370392; exit=0; EXPECT=matched; output-sha256=fa7ba988b7f6285e02b2be99cd5e02fe55ce624b4bf309c6a25d3fc10f32467d; output-bytes=236; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G11: migrations apply on an empty database, match the models, and downgrade to nothing
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -p no:cacheprovider -q services/api/tests/test_migrations.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=7af45ab9142c8208a98e36e5c0f5afd63b57be7cdf7c530a877b3ec2361e2eab; exit=0; EXPECT=matched; output-sha256=a15a40f40451c6918299ebc859dc1553f08feb9ee52a371415700087791dabfc; output-bytes=235; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [x] G12: the engine, worker and API suites together pass against real Postgres and Redis and nothing is skipped except requires_keys tests
  CHECK: uv run --env-file .unlazy/axon/b11-test.env pytest -q -p no:cacheprovider -rs | grep -E "^(SKIPPED|FAILED|ERROR)|passed" | grep -v requires_keys
  EXPECT: /(^|\n)\d+ passed[ ,]/
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=a775549d58d114b06cb1b9bef2a4756f699cc01adf2c4d44fd6494145ba1470c; exit=0; EXPECT=matched; output-sha256=d0d1bfb3e4f9afb27aa94fcb065735c367422da629b24120cb2d4616968930d3; output-bytes=195; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries

- [ ] G13: the CI compose job on the PR head passes (it starts the stack, migrates to the new head and prints COMPOSE HEALTHY); this sandbox has no Docker daemon, so CI is the authority
  CHECK: gh api repos/eax0106/axon/commits/phase/b11-training-knowledge/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\" and (.name | test(\"compose\"))) | .name] | join(\",\")"
  EXPECT: compose
  CWD: ../../..
  EVIDENCE: pending

- [ ] G14: CI on the PR head passes the test jobs on ubuntu, macos and windows
  CHECK: gh api repos/eax0106/axon/commits/phase/b11-training-knowledge/check-runs --jq "[.check_runs[] | select(.conclusion == \"success\") | .name] | join(\",\")"
  EXPECT: /^(?=.*ubuntu)(?=.*macos)(?=.*windows)/
  CWD: ../../..
  EVIDENCE: pending

- [x] G15: docs/phases/b11.md exists with a Gate results section
  CHECK: node -e "const fs=require('fs');const t=fs.readFileSync('docs/phases/b11.md','utf8');if(!t.includes('Gate results'))process.exit(1);console.log('B11-DOC-OK')"
  EXPECT: B11-DOC-OK
  CWD: ../../..
  EVIDENCE: automatic-evidence=v1; definition-sha256=5f71f6e140dd11274166d4ea94eed3f7a890bdd3d2c6a98317ec8fbe6ef48ac5; exit=0; EXPECT=matched; output-sha256=93602cfc8992d86c2146765acf5013f4f7fce7b982e0f530dac0a21e9cb712a5; output-bytes=11; shell=/bin/sh; cwd=/home/claude/axon; path=7f4fb4b02918/15 entries
