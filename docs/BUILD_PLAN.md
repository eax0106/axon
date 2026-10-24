# Build Plan — V1 (Stage A, 1:1 Outpero parity)

Status: agreed direction, 2026-10-24. Languages for V1: **Telugu, English, Hindi**. Stages B and C are parked.

## 0. Ground rules from the owner

1. **No fake providers.** The product contains only real integrations. Each outside service gets a **provider adapter**: a "plug" written against that vendor's real API, waiting for its keys.
2. **Keys come last.** We write the whole codebase first. Then I ask for every key in one list (`docs/WIRING_CHECKLIST.md`), you provide them, I plug them in and we run real calls. Real calls are the only proof of quality.
3. **Business paperwork is yours.** Company, GST, domain, legal and trademark are on the checklist and don't block coding.
4. **Runs anywhere.** The code runs locally on macOS, Windows and Linux, and deploys unchanged to web hosting.
5. **Discipline.** Every phase has a gate ledger (unlazy `GATES.md`) with runnable checks. A phase is done only when its gates pass.

## 1. What "plug and play" means in code

```
services/api/app/providers/
  base.py            # interfaces: TelephonyProvider, SpeechToTextProvider, LLMProvider,
                     #   TextToSpeechProvider, PaymentProvider, ObjectStorageProvider,
                     #   EmailProvider, WhatsAppProvider, CalendarProvider, SheetsProvider,
                     #   LeadSourceProvider, NumberKycProvider
  registry.py        # picks the adapter named in settings; reports configured / missing-key
  telephony/vobiz.py
  stt/sarvam.py      stt/smallest.py
  llm/gemini.py      llm/sarvam.py
  tts/sarvam.py      tts/smallest.py     tts/cartesia.py
  payments/razorpay.py
  storage/r2.py      (S3-compatible, so any S3 store works)
  email/<vendor>.py
  whatsapp/interakt.py   whatsapp/aisensy.py
  google/calendar.py     google/sheets.py
  leads/meta_lead_ads.py
```

- Every adapter implements its vendor's documented API: endpoints, auth headers, audio formats, webhook signature checks.
- Settings come from environment variables (`.env` locally, a secrets store when hosted). `.env.example` lists every key, with a comment naming the vendor page it comes from.
- **Missing key behaviour.** The app still boots without keys. Any feature that needs a missing key returns a clear `503 provider_not_configured` naming the key, and `GET /admin/providers` shows each provider as `configured`, `missing_key` or `unhealthy`. Nothing pretends to work.
- **Verification without fakes.** Adapter contract tests call the real vendor APIs. They're tagged `requires_keys` and stay skipped until keys exist; once keys arrive they become mandatory gates.
- **Real local services, not fakes.** Postgres, Redis and object storage run locally for real. Everything internal is fully testable today: the database, API, dialer rules, credit ledger, campaigns, webhooks and the prompt compiler.

## 2. Stack

| Layer | Choice |
|---|---|
| Language and runtime | **Python 3.12** (pinned with `.python-version` and uv; Pipecat doesn't support 3.14 yet) |
| API | FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Database | PostgreSQL 16, with pgvector for knowledge search |
| Queue and scheduling | Redis + Arq workers + a dialer/scheduler process |
| Voice engine | Pipecat. Our own Vobiz serializer (start from Pipecat's Plivo one), Silero VAD + Smart Turn v3 |
| Auth | Our own email/password with argon2 and JWT sessions; Google sign-in plug added later. Not tied to any vendor, so it works offline and on any host |
| Frontend (Track 2) | React + Vite + TypeScript, Tailwind, Radix, Motion, GSAP, react-three-fiber |
| Tooling | uv (Python), pnpm (Node 20 LTS), ruff, mypy, pytest, Playwright for UI later |

## 3. Runs everywhere

- **Docker Compose** is the universal way to run. One `docker compose up` starts api, engine, worker, scheduler, postgres, redis and web identically on macOS (Intel or Apple silicon), Windows (Docker Desktop with WSL2) and Linux. Images are built for both `linux/amd64` and `linux/arm64`.
- **Native dev path:** uv and pnpm, with the same commands on all three operating systems. Project tasks are Python or Node scripts (`tasks.py` / `package.json` scripts), not bash, so they work on Windows too. Paths go through `pathlib`; `.gitattributes` fixes line endings.
- **Hosting:** the same containers deploy to any container host. Twelve-factor config, `/healthz` and `/readyz` endpoints, a migrations job, stateless api and engine, recordings in object storage. Recommended region is India (for example AWS Mumbai or Hyderabad) for latency to Vobiz and Sarvam.
- **Local real calls:** Vobiz needs a public URL for its answer URL and audio stream, so during wiring a tunnel (cloudflared) exposes the local engine. In hosting, the real domain replaces the tunnel.

## 4. Repository layout

```
/ (monorepo)
  services/api        FastAPI app, providers/, domain modules, Alembic
  services/engine     Pipecat voice engine (per-call pipelines, Vobiz serializer)
  services/worker     Arq jobs: post-call, webhooks, renewals, retries, campaign ticks
  apps/web            Dashboard (Track 2)
  packages/contracts  OpenAPI schema and generated TypeScript client
  deploy/             docker-compose.yml, Dockerfiles, hosting manifests
  docs/               PLAN.md, WIRING_CHECKLIST.md, ARCHITECTURE.md, PARITY.md, DESIGN_DIRECTION.md
  CLAUDE.md / AGENTS.md   project memory for any agent session
  .unlazy/            gate ledgers per phase (untracked)
```

## 5. Track 1 — backend build order

Each phase ends with a gate ledger. "Local" gates run now; "keys" gates run after wiring.

| # | Phase | Contents | Done when (local) | Done when (keys) |
|---|---|---|---|---|
| B0 | Foundation | Monorepo, Docker Compose, Python 3.12, CI (lint, types, tests), settings, provider registry, `/admin/providers` | `docker compose up` healthy on macOS; CI also green on Windows and Linux runners | — |
| B1 | Data model and auth | Full Postgres schema (accounts, employees, versions, voices, numbers, leads, calls, call events, campaigns, contacts, DNC, consent, wallet ledger, payments, api keys, webhooks, notifications, audit), migrations, auth, roles | Migrations apply on an empty DB; auth tests pass | — |
| B2 | Voice engine | Pipecat pipeline, Vobiz serializer (answer XML, `start`/`media`/`playAudio`/`checkpoint`/`clearAudio`), barge-in, Indic sentence splitter (`।` `॥`), call-length cap, silence watchdog, recording, cost meter, live events over WebSocket | Unit tests on serializer framing and the splitter; pipeline assembles | Real call in Telugu, Hindi and English; replies under 1 s, measured |
| B3 | Speech and LLM adapters | Sarvam STT (Saaras, codemix) and TTS (Bulbul), Smallest TTS and STT, Cartesia TTS, Gemini 2.5 Flash, Sarvam LLM as second option; voice tiers Value / Standard / Premium | Adapters type-check; contract tests present and skipped | Contract tests pass against the real APIs |
| B4 | AI employee builder | Brief (typed or spoken), follow-up questions, draft agent, script sections, end rules, permanent FAQ, strictness 1–5, pre-call and captured variables, prompt compiler, voice and ambience settings, lifecycle (draft / training / live / paused), publish, last 3 versions, restore, switch mode, reset, test call, web call, chat sandbox | Prompt compiler and lifecycle tests pass | Drafting and test calls work |
| B5 | Instant | Intake URL + secret (rotate, reveal), intake log (accepted / deduplicated / rejected), dial delay, calling window (6 AM–10 PM hard limit), out-of-window rules, retry ladder up to 10 attempts, queue console, redial, Meta Lead Ads, Sheets | Dialer rule tests (hours, retries, dedupe, DNC) pass | Meta test lead triggers a real call |
| B6 | Post-call and data | Post-call job (summary, sentiment, outcome, captured fields, nothing invented), conversations, call detail, leads (one per phone number), notes, exports, caller memory, callback scheduling, stats and analytics, notifications | Aggregation and export tests pass | Real call produces a correct record |
| B7 | Billing and numbers | Credit ledger (1 credit = ₹1), per-second metering from pickup, tier rates, spend caps, low-balance alerts, statements, GST invoices, Razorpay orders and webhooks, Vobiz number inventory, quote, purchase, KYC (PAN + DigiLocker Aadhaar), ₹649 renewals, grace and release, channels per number; number types (regular / 140 / 1600) and a configurable purpose-by-number-type rule table checked before every dial (see DECISIONS) | Ledger always balances (property tests); renewal state machine tests | Test-mode payment and number purchase |
| B8 | Bulk | Contacts (CSV, paste, manual) and column mapping, saved lists, window / days / holidays (9 AM–9 PM hard limit), concurrency 1–20, skip DNC, retries 1–9, schedule and repeat, cross-campaign dedupe, exclusion list, consent confirmation, live panel actions, campaign queue on a shared number | Scheduler tests with simulated time pass | Real 20-contact campaign |
| B9 | Inbound | Answer on the attached number, opening hours, greetings, recording disclosure, messages and callbacks, missed callers and auto call-back, daily summary email, transfer to a human, outbound employees answering their own callbacks | Routing and state tests pass | Real inbound call answered |
| B10 | In-call actions | Tool framework, custom HTTP API tool, Google Calendar booking, Google Sheets read and write, WhatsApp send, all opt-in per employee | Tool schema and HTTP tool tests (against a local real endpoint) pass | Booking and WhatsApp confirmation on a real call |
| B11 | Training and knowledge | Facts and rules from text, voice or photo; review step; documents with pgvector retrieval; struggle detector and teaching suggestions | Retrieval and rules-precedence tests pass | Photo price list changes answers |
| B12 | Developer platform | API keys, versioned public API, OpenAPI, Postman export, request log, signed webhooks for 6 events (deliveries, resend, rotate secret, test), per-employee webhook triggers | Signature and retry tests pass; OpenAPI validates | n8n receives events |
| B13 | Reliability and admin | Per-leg failover mid-call (STT, LLM, TTS) with health scoring, Premium falling back to Value price, apology and clean hangup, provider balance and cost tracking, capacity limits, admin console APIs, logged impersonation | Failover tests by forcing real adapters into error paths (timeouts, bad credentials) | Killing one provider mid-call keeps the call alive |
| B14 | Hardening | Parity checklist against the Outpero map, load test, security review, backups, runbooks | `PARITY.md` 100% for backend items | Native-speaker QA in Telugu, Hindi and English |

## 6. Track 2 — dashboard UI

- Follows `DESIGN_DIRECTION.md` (ALTERX design language, heavy but purposeful motion).
- Starts once the B4–B6 APIs are stable, then grows phase by phase against the real API through the generated TypeScript client. No mock data in the product.
- Marketing site and help centre come after the dashboard.

## 7. Track 3 — wiring and launch

1. I hand you `docs/WIRING_CHECKLIST.md`: every key, where to get it, what it unlocks, and the env var it goes in.
2. You provide the keys. I put them into `.env` (never committed) and run `GET /admin/providers` until every one shows `configured`.
3. Contract tests (`requires_keys`) run, then the first real call through a tunnel, latency tuning per language, and the "keys" column of every phase's gates.
4. Hosting: deploy the containers to an India region with the domain and TLS. Then a beta with your own number.

## 8. Wiring checklist (seed for `docs/WIRING_CHECKLIST.md`)

| Item | Unlocks | Who |
|---|---|---|
| Company + GST, legal opinion (TRAI 140-series vs 10-digit numbers, DPDP) | Razorpay, Vobiz KYC, DLT, launch | You |
| Domain + Cloudflare (DNS, R2, Turnstile) | Public URLs, recordings, signup protection | You, then me |
| Vobiz (auth id + token, numbers, KYC sub-accounts) | All calls | You |
| Sarvam API key | Speech-to-text, Value voices, optional LLM | You, then me |
| Gemini API key | LLM | You, then me |
| Smallest API key | Standard voices, backup speech-to-text | You, then me |
| Cartesia API key | Premium voices | You, then me |
| Razorpay key id + secret + webhook secret | Credit top-ups | You |
| Email provider key | Alerts and summaries | Me |
| Google Cloud OAuth client (verified app) | Calendar and Sheets | You, then me |
| Meta app (Lead Ads webhook) | Instant leads from ads | You, then me |
| WhatsApp BSP (Interakt or AiSensy) + approved templates | WhatsApp actions | You |
| Hosting account (India region) | Deployment | You, then me |
| Test phones + Telugu and Hindi native speakers | Quality checks | You |

## 9. How we work

See `docs/WAY_OF_WORKING.md` (session roles, phase loop, mandatory skills, permissions) and `docs/ORCHESTRATION.md`. Security testing with Strix runs once after B14 (phase SEC in `docs/PLAN.md`).
