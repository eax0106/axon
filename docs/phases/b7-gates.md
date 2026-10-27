# Gates: B7 Billing and numbers

OWNS: services/api/app/**, services/api/migrations/**, services/api/tests/**, services/engine/**, services/worker/**, uv.lock, pyproject.toml, deploy/**, docs/phases/b7.md, docs/PARITY.md, docs/DECISIONS.md, docs/WIRING_CHECKLIST.md, .env.example, CLAUDE.md

Scope: a prepaid credit wallet (1 credit = one rupee) with an append-only ledger, per-second call billing from the carrier's own record, spend caps and low-balance alerts, Razorpay top-ups, statements and GST invoices; Vobiz number inventory, quote, purchase and KYC; number renewals with grace and release; one number per employee with extra channels; and the purpose x number-type dial rule table that replaces the allow-everything hook.

- [ ] G0: this ledger states outcomes that can fail
  CHECK: node /Users/havishvardhan/.claude/skills/unlazy/scripts/gate-lint.mjs .unlazy/axon/gates/b7.md
  EXPECT: LINT OK
  EVIDENCE: pending

- [ ] G1: locked sync, ruff check and ruff format are clean
  CHECK: uv sync --locked --all-packages && uv run ruff check . && uv run ruff format --check . && echo LINT-OK
  EXPECT: LINT-OK
  EVIDENCE: pending

- [ ] G2: mypy strict passes over every package
  CHECK: uv run mypy && echo MYPY-OK
  EXPECT: MYPY-OK
  EVIDENCE: pending

- [ ] G3: the credit ledger always balances: a seeded random loop of top-ups, charges, refunds and adjustments keeps balance_after equal to the running sum of amounts, the account balance equal to the ledger total, repeated references post once, and a spend that would overdraw is refused
  CHECK: uv run --env-file .unlazy/axon/b7-test.env pytest -p no:cacheprovider -q services/api/tests/test_ledger.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  EVIDENCE: pending

- [ ] G4: parallel charges: the same reference posted by many workers at once lands exactly once, distinct charges all land and the balance is exact, and spends racing for the last credits never overdraw
  CHECK: uv run --env-file .unlazy/axon/b7-test.env pytest -p no:cacheprovider -q services/api/tests/test_ledger_concurrency.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  EVIDENCE: pending

- [ ] G5: call billing: charged per second of the carrier's own record (billsec) at the call's tier rate, never from the unsigned callback, unanswered and test calls are free, a call with no carrier record is never charged and is surfaced for reconciliation, and re-running charges nothing twice
  CHECK: uv run --env-file .unlazy/axon/b7-test.env pytest -p no:cacheprovider -q services/api/tests/test_call_billing.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  EVIDENCE: pending

- [ ] G6: credit policy: 50 free credits once per account, dialing blocked at zero balance, hourly spend cap, low-balance alert in the app and by email at most once a day, and the AI-use fee for the builder, chat sandbox, voice preview, analysis and re-analysis charged through the ledger
  CHECK: uv run --env-file .unlazy/axon/b7-test.env pytest -p no:cacheprovider -q services/api/tests/test_credit_policy.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  EVIDENCE: pending

- [ ] G7: Razorpay: order request pinned in paise, checkout signature and webhook signature verified (valid, wrong, tampered), a payment credits the wallet exactly once whether the browser or the webhook comes first, and missing keys give 503
  CHECK: uv run --env-file .unlazy/axon/b7-test.env pytest -p no:cacheprovider -q services/api/tests/test_razorpay.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  EVIDENCE: pending

- [ ] G8: statements, running-balance transactions, per-employee usage and GST invoices: rate and codes from config, CGST plus SGST or IGST by state, sequential numbers, all scoped to the account
  CHECK: uv run --env-file .unlazy/axon/b7-test.env pytest -p no:cacheprovider -q services/api/tests/test_statements.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  EVIDENCE: pending

- [ ] G9: number store: inventory search, quote, purchase debits the wallet and needs KYC first, vendor requests pinned, release, scoped, 503 without keys
  CHECK: uv run --env-file .unlazy/axon/b7-test.env pytest -p no:cacheprovider -q services/api/tests/test_numbers_store.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  EVIDENCE: pending

- [ ] G10: KYC: PAN then Aadhaar through DigiLocker, the verified holder is reused for later numbers, the full PAN is never stored
  CHECK: uv run --env-file .unlazy/axon/b7-test.env pytest -p no:cacheprovider -q services/api/tests/test_kyc.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  EVIDENCE: pending

- [ ] G11: number renewal state machine under simulated time: renews from credits, falls into grace when credits run out, recovers on top-up, releases at the end of grace, detaches and pauses its employee, deletes nothing else, and never charges a period twice
  CHECK: uv run --env-file .unlazy/axon/b7-test.env pytest -p no:cacheprovider -q services/api/tests/test_number_renewals.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  EVIDENCE: pending

- [ ] G12: one number per employee, extra channels per number, attach and detach scoped to the account and refusing inactive numbers
  CHECK: uv run --env-file .unlazy/axon/b7-test.env pytest -p no:cacheprovider -q services/api/tests/test_number_attach.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  EVIDENCE: pending

- [ ] G13: dial rule table: every default purpose x number type x context pairing, the strict and relaxed Instant setting, fail closed when a rule is missing, and a plain-words reason
  CHECK: uv run --env-file .unlazy/axon/b7-test.env pytest -p no:cacheprovider -q services/api/tests/test_dial_rules.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  EVIDENCE: pending

- [ ] G14: rules in force: the dialer cancels a blocked pairing with the reason, test calls go through do-not-call and the rule table, and free test calls need the owner's phone verified by a one-time code
  CHECK: uv run --env-file .unlazy/axon/b7-test.env pytest -p no:cacheprovider -q services/api/tests/test_dial_policy_integration.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  EVIDENCE: pending

- [ ] G15: real-use contract tests for Razorpay test mode, Vobiz inventory and Resend exist, are tagged requires_keys and all skip without keys
  CHECK: uv run --env-file .unlazy/axon/b7-test.env pytest -p no:cacheprovider -q -rs services/api/tests/test_billing_contract.py
  EXPECT: /(^|\n)(\d+ passed, )?\d+ skipped in /
  EVIDENCE: pending

- [ ] G16: migrations apply on an empty database, match the models, and downgrade to nothing
  CHECK: uv run --env-file .unlazy/axon/b7-test.env pytest -p no:cacheprovider -q services/api/tests/test_migrations.py
  EXPECT: /(^|\n)\d+ passed[ ,]/
  EVIDENCE: pending

- [ ] G17: full suite passes against real Postgres and Redis and nothing is skipped except requires_keys tests
  CHECK: uv run --env-file .unlazy/axon/b7-test.env pytest -q -p no:cacheprovider -rs
  EXPECT: /^(?![\s\S]*SKIPPED \[\d+\] (?:(?!requires_keys)[^\n])*\n)[\s\S]*\n\d+ passed, \d+ skipped/
  EVIDENCE: pending

- [ ] G18: compose (own project axonb7 and ports) is healthy and every image is under 1 GB unpacked
  CHECK: uv run --env-file .unlazy/axon/b7-compose.env python scripts/compose_smoke.py
  EXPECT: COMPOSE HEALTHY
  EVIDENCE: pending

- [ ] G19: CI on the PR head passes on ubuntu, macos and windows plus the compose job
  CHECK: gh pr checks phase/b7-billing-numbers --json name,bucket --jq "[.[] | select(.bucket == \"pass\") | .name] | join(\",\")"
  EXPECT: /^(?=.*ubuntu)(?=.*macos)(?=.*windows)(?=.*compose)/
  EVIDENCE: pending

- [ ] G20: docs/phases/b7.md exists with a Gate results section
  CHECK: node -e "const fs=require('fs');const t=fs.readFileSync('docs/phases/b7.md','utf8');if(!t.includes('Gate results'))process.exit(1);console.log('B7-DOC-OK')"
  EXPECT: B7-DOC-OK
  EVIDENCE: pending

