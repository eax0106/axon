# Outpero 1:1 Rebuild — Research Blueprint

Date: 2026-10-24 · Builds on the 2026-10-21 teardown (`outpero-rebuild-report.md`).
Scope: what to build, how to build it, in what phases. No timeframes, by request. UI design and branding are deferred until you choose them.

---

## 1. Summary (plain language)

We are rebuilding Outpero's product feature for feature. That means an "AI employee" that phones leads, works through call lists, and answers a business's phone, in Indian languages, with prepaid per-minute billing. Only the UI look and the brand will differ.

Outpero's app is public enough to map its whole product: about 170 API endpoints, its agent data model, every channel setting, and its billing and number-KYC flows (§3). Everything it does can be built from parts you can rent:
- **Phone lines:** Vobiz.
- **Speech:** Sarvam, Smallest and Cartesia.
- **AI brain:** Gemini.
- **App plumbing:** Postgres, Redis and Razorpay.

Plus one open-source voice framework, Pipecat (§4).

Two things matter most:
1. **The voice loop.** It must answer within about 1 second, in Telugu, Hindi and the other languages, with natural interruptions. Every phase depends on this, so we build it first.
2. **Compliance.** India's TRAI rules now say promotional calls should come from 140-series numbers, not ordinary 10-digit numbers. Outpero calls from ordinary 10-digit numbers. Copying that exactly carries legal risk, so get a lawyer's view before launch (§6).

For your 6 first languages (English, Telugu, Hindi, Tamil, Malayalam, Odia), speech-to-text and text-to-speech exist for all of them. One gap: Odia has no confirmed premium-voice provider yet (§5).

The build has 3 stages:
- **Stage A:** 15 phases to reach 1:1 parity.
- **Stage B:** features that beat Outpero and other players.
- **Stage C:** language expansion.

---

## 2. Gates for this report

| Gate | Status |
|---|---|
| Map every Outpero screen, API area, data object and flow | met (§3) |
| Choose a build approach and stack for each layer, with reasons | met (§4) |
| Language coverage for EN, TE, HI, TA, ML, OR | met, with an Odia premium gap (§5) |
| Compliance requirements | met at research level; legal review needed (§6) |
| Features to beat existing players | met (§8) |
| Build phases, no timeframes | met (§7) |
| Design and branding question at the end | met (end) |

---

## 3. Findings — the complete Outpero map

Sources: S1 (public app bundle at app.outpero.com, re-read 2026-10-24) and S2 (in-app help centre). Both are T1 primary artefacts, so the features are `verified` as existing. How they work internally is `inference`.

### 3.1 Product areas (screens)

The app's lazy-loaded code chunks name every screen:
- **Main app:** Dashboard, Hire (agent creation), Employees, EmployeeDetail, Teach (training), TalkPage, InstantPage and InstantQueueConsole, BulkPage and CampaignCreate, InboundPage, LeadsPage, Conversations and RichCallLog, Performance, Numbers, Billing, Developers, SettingsPage, Onboarding and ChannelFirstRun, Docs.
- **Legal pages:** Terms, Privacy, Refund, Cookies, Acceptable Use, Security.
- **Internal:** Admin and SystemHealth.

### 3.2 API surface (non-admin)

| Area | Endpoints (abridged) |
|---|---|
| Account | `/accounts/me`, `accept-terms`, `caller-memory` (list, reset), `set-password` |
| AI builder | `/ai/brief-questions`, `/ai/draft-agent`, `/ai/edit-flow`, `/ai/structure-prompt`, `/ai/voice-prompt`, `/ai/transcribe-chunk` |
| Employees | CRUD; `activate`, `deactivate`, `publish`, `revert`, `reset`, `switch-mode`, `versions` + `restore`; `script-bundle` (+ preview); `pre-variables`, `capture-variables`; `dialer-settings`, `inbound-settings`; `number`; `stats`; `setup-help` |
| Testing | `outbound-test-call`, `web-test-call`, `test-lead`, `call-number` |
| Actions | `actions`, `custom-apis` (+ test, + whatsapp), `google-calendar` (connect, test-booking, reuse-available) |
| Delivery | `deliveries` (+ test), `webhook-events`, `lead-webhook` (reveal / rotate secret, test) |
| Training | `training`, `training/suggestions` (+ dismiss) |
| Campaigns | CRUD; `launch`, `pause`, `resume`, `cancel`, `cancel-callbacks`, `retry-exhausted`, `restore-not-called`, `save-as-list`, `live`, `analytics`, `contacts` (+ CSV, bulk-action, per-contact call-now / cancel / retry); `/capacity/campaigns/{id}/preview` |
| Contacts & DNC | `/contact-lists`, `/dnc` (+ bulk) |
| Calls & leads | `/calls` (+ live, summary, by-agent, `{id}/redial`); `/leads` (+ breakdown, summary, fields, notes) |
| Inbound | `/inbound/messages` (+ done), `/inbound/missed` |
| Numbers | `/numbers/vobiz/{inventory, quote, purchase, holders, kyc/verify-pan, kyc/digilocker/initiate, kyc/digilocker/verify}`; parallel `/numbers/voicelink/kyc/{step1, pan, gst, aadhaar-init, aadhaar-callback, documents, locations, final-submit, status}` |
| Billing | `/wallet` (+ `topup/order`, `topup/verify`), `/billing/{payments, statement, transactions, usage, invoice, settings, setup-call}` |
| Developer | `/developer/keys` (+ revoke), `/developer/webhooks` (+ deliveries, resend, rotate-secret, test), `/developer/requests`, `/developer/status` |
| Stats | `/stats/{dashboard, performance, analytics, instant, bulk, call-health}` |
| Misc | `/notifications`, `/announcements`, `/support/{chat, feedback, rating}`, `/voices`, `/config`, `/public/signup-status` |
| Lead intake | `POST /lead-intake/{connection-id}` with header `X-Outpero-Lead-Secret` (S2) |

### 3.3 Employee (agent) data model (S1)

```
name, role, mode (instant|bulk|inbound), language, extra_languages[],
voice_provider, voice_id, tts_speed, ambient_sound, ambient_volume,
welcome_message, agent_information, sections[] (call flow), call_end_rules,
script_adherence (1–5), style_pack_enabled, power_prompting,
ai_acknowledgement_enabled, variables[] (pre-call), capture variables,
inbound: open_hours, greetings{caller, returning_lead}, transfer_number, transfer_when
dialer: calling_window, calling_days, retry_enabled, retry_ladder_min[], max_attempts,
        respect_dnc, dedup_recent_days, shared_line_calling_enabled
```

Voice objects carry `native_language`, `accent`, `tone_tags`, `public_name`, and per-language `language_scores` (≥0.85 = "great", ≥0.7 = "good", lower = "accented"). Engine settings are grouped as transcriber, synthesizer, llm and task.

### 3.4 Features not on their marketing site (S1)

- **Live call transfer to a human:** `transfer_number`, `transfer_when` on inbound.
- **Spend caps:** per hour (`spend_cap_inr_hr`).
- **Billing rates:** a "hire fee" per employee exists but is set to 0. An "AI per use" fee is ₹0.2. A first-hire bonus exists.
- **Analytics:** agent leaderboard, best hour to call, connect / qualify / conversion %, "within 60 s" speed metric, call-health stats.
- **A second telephony provider:** "voicelink", with GST and location KYC steps.
- **Running the business:** the admin side has its own Postgres disk-runway monitor. **Inference:** the database is self-hosted Postgres, with Supabase used for auth.

### 3.5 Behaviour rules (S2)

All behaviour rules are as listed in the 10-21 teardown. In short:
- **Calling hours:** Bulk 9 AM–9 PM, Instant 6 AM–10 PM.
- **Retries:** up to 10 attempts on Instant; 1–9 on Bulk.
- **Bulk concurrency:** 1–20 calls at once.
- **Call length:** 10 min max by default (10 s – 60 min).
- **Versions:** last 3 published versions kept.
- **Failover:** each of speech-to-text, AI and text-to-speech fails over to a backup provider. A Premium voice falls back to a Value voice at the Value price, never the other way.
- **Billing:** only from pickup. Low-balance email at about ₹50.

---

## 4. How to build each layer (findings + recommendation)

### 4.1 Telephony — Vobiz

- **Inbound calls:** Vobiz POSTs to your answer URL. You return XML with `<Stream bidirectional="true" contentType="audio/x-mulaw;rate=8000">wss://…</Stream>` (S3, T1).
- **Outbound calls:** `POST /api/v1/Account/{auth_id}/Call/` with `from`, `to` and `answer_url` (S4, T3 community docs).
- **WebSocket messages:**
  - Vobiz sends `start` (streamId, mediaFormat) and `media` (base64 audio).
  - You send `playAudio` (base64 raw mono Linear16 at 8/16/24 kHz, **no WAV header**), `checkpoint`, and `clearAudio` for barge-in.
  - Vobiz replies with `playedStream` / `clearedAudio` (S3).
- **Inference:** Vobiz's API paths and XML match Plivo's, so Pipecat's Plivo serializer is the starting point. The Vobiz serializer is our own small adapter — untested.
- **Mid-call stream:** a REST endpoint can attach a stream to a call that's already live (S4).

### 4.2 Voice engine — Pipecat (recommended)

- Pipecat is a Python pipeline. It ships serializers for Twilio, Plivo, Exotel, Telnyx and Vonage, plus a generic WebSocket path for others (S5, T1).
- **Turn-taking:** Silero VAD plus **Smart Turn v3**. This open model (BSD-2, about 8M parameters, runs on CPU) decides from the audio whether the caller has finished speaking. It is Pipecat's default (S6, T1). It replaces Outpero's Bolna-style "endpointing ms" and "words to interrupt" settings with something more natural. We still expose those settings.
- **Why not copy Sarvam's own Vobiz sample:** it skips frameworks and uses a simple energy-level detector (S3). That's fine for a demo. It is weak for real interruptions, failover and tools.
- Pipeline per call:

  ```
  Vobiz WS → VobizSerializer → VAD + SmartTurn → STT (stream) → context aggregator
  → LLM (tools) → sentence splitter → TTS (stream) → ambience mixer → VobizSerializer → Vobiz
  ```

  Side tasks during the call: live transcript to Redis, cost meter, call-length cap, silence watchdog and failover supervisor.
- **Sentence splitting** must include the Indic full stops `।` and `॥` (S3).

### 4.3 Speech and LLM providers

| Leg | Primary | Fallback | Notes |
|---|---|---|---|
| STT | Sarvam `saaras` (v3/v4, `mode: codemix`) | Smallest Pulse; Soniox | saaras covers 22 Indian languages + English (S7); Pulse covers 32–38 languages incl. Odia (S9) |
| LLM | Gemini 2.5 Flash (matches Outpero) | `sarvam-105b` or a second vendor | Sarvam's LLM needs ≥1500 tokens per turn because its reasoning counts against the limit (S3) |
| TTS Value | Sarvam Bulbul (v3 / v4-flash) | Smallest | Bulbul: 11 languages incl. Odia (S7) |
| TTS Standard | Smallest Lightning v3.1 | Sarvam | 9 Indian languages incl. Odia (S9) |
| TTS Premium | Cartesia Sonic | Smallest | Telugu, Tamil and Malayalam yes; Odia only claimed for Sonic-3.6, unconfirmed (S8) |

### 4.4 Platform

| Layer | Choice | Why |
|---|---|---|
| Repo | Monorepo: `apps/web` (dashboard), `apps/site` (marketing), `services/api`, `services/engine`, `services/worker`, `packages/shared` | One place for shared types and config |
| API | Python FastAPI + SQLAlchemy + Alembic | Same language as the engine; Outpero's API is also FastAPI-style |
| DB | Postgres (managed). Supabase for auth + Postgres + Realtime | Matches Outpero; Realtime gives live dashboards cheaply |
| Queue / scheduler | Redis + a worker (Arq or Dramatiq) + a dialer loop | Dial jobs, retries, campaigns, renewals, post-call jobs |
| Engine hosting | Containers in an India region (AWS Mumbai/Hyderabad), auto-scaled on concurrent calls | Latency to Vobiz and Sarvam |
| Storage | Cloudflare R2 (recordings, docs, photos) | Matches Outpero; no egress fees |
| Payments | Razorpay Orders + webhook verify | Matches Outpero; card + UPI |
| Frontend | React + Vite + TypeScript + TanStack Query + Tailwind; design system TBD (your answer) | Matches Outpero's SPA |
| Marketing site | Astro or Next.js static, SEO pages (blog, glossary, compare) | Outpero runs its marketing on a separate Vercel deployment |
| Analytics | PostHog, onboarding flow only | Matches their privacy stance |
| Email | Transactional email provider | Low balance, daily inbound summary, alerts |
| Integrations | Google Calendar + Sheets OAuth; Meta Lead Ads webhook; WhatsApp BSP (Interakt / AiSensy); Zapier / Pabbly / n8n via webhook | Same as Outpero |

### 4.5 Core data model (inference, from §3)

```
accounts, users, account_settings, kyc_holders
employees, employee_versions (script bundle snapshot, max 3 kept), employee_actions,
  custom_apis, calendar_connections, deliveries (per-employee webhooks)
knowledge_items (fact|rule), knowledge_docs (+ chunks/embeddings), training_suggestions
voices (provider, voice_id, tier, native_language, accent, language_scores)
numbers (provider, did, channels, holder_id, renews_on, status)
lead_connections (intake URL + secret), lead_intake_log
leads (one per phone per account), lead_fields, lead_notes, caller_memory
calls (direction, channel, employee, lead, campaign, status, outcome, sentiment,
  duration_s, credits_charged, recording_url, transcript, summary, captured{})
call_events (timeline), scheduled_calls (callbacks / retries)
campaigns, campaign_contacts, contact_lists, dnc_entries, consent_attestations
wallet_ledger (topup, call, number, refund, bonus, adjustment), payments, invoices
api_keys, webhook_endpoints, webhook_deliveries, api_request_log
notifications, announcements, audit_log (incl. staff impersonation)
```

---

## 5. Languages — EN, TE, HI, TA, ML, OR

| Language | STT | TTS Value (Sarvam) | TTS Standard (Smallest) | TTS Premium (Cartesia) |
|---|---|---|---|---|
| English | yes | yes | yes | yes |
| Hindi | yes | yes | yes | yes |
| Telugu | yes | yes | yes | yes |
| Tamil | yes | yes | yes | yes |
| Malayalam | yes | yes | yes | yes |
| Odia | yes (Sarvam, Pulse) | yes | yes | **unconfirmed** — offer Odia on Value/Standard only until tested |

Sources: S7, S8, S9. Provider docs say these languages are supported. Call quality on noisy 8 kHz phone audio is **untested**. Each language needs a native-speaker test pass: transcription accuracy, voice naturalness, and code-mixing with English.

Easy next additions from the same providers: Kannada, Marathi, Bengali, Gujarati, Punjabi (Bulbul and Lightning cover them). Beyond that, Saaras speech-to-text covers 22 Indian languages, but voice coverage is thinner.

---

## 6. Compliance (findings)

- **TRAI TCCCPR amendment (Feb 2025):**
  - Ordinary 10-digit numbers may not be used for telemarketing.
  - **140-series** numbers are for promotional calls and require registration with telecom operators.
  - **1600-series** numbers are for service and transactional calls, mainly regulated finance and government.
  - (S10, T1 TRAI press release; S11, T2.)
- **Gap with 1:1:** Outpero sells ordinary 10-digit numbers for lead calls. Whether calling a lead who just enquired counts as "promotional" needs a lawyer's opinion. Plan for both 140-series support and DLT registration in the numbers module.
- **DPDP Rules 2025:**
  - Notified 13–14 Nov 2025.
  - Core duties apply from **13 May 2027**: itemised consent notice, purpose limitation, security, breach notice, data-subject rights (S12, T2).
  - Build in now: consent records, recording disclosure, retention and deletion, data export and erasure.
- **Copy these from Outpero:**
  - calling hours enforced on the server
  - consent attestation per campaign and per lead source
  - automatic do-not-call when a caller asks
  - recording disclosure before the greeting
  - PAN + Aadhaar (via DigiLocker) owner verification for numbers

---

## 7. Recommendations — the build plan

### Stage A — 1:1 parity (phases in build order)

**Phase 0 — Accounts and prerequisites (you)**

These need your identity or company, so you complete them and I wire them in:
- company and GST
- Vobiz account, including the KYC sub-account API
- Sarvam, Smallest, Cartesia and Gemini keys
- Razorpay business account
- Google Cloud project with OAuth app verification for Calendar and Sheets
- Meta developer app for Lead Ads
- WhatsApp BSP account
- Cloudflare account with R2 and the domain
- email provider
- a legal opinion on TRAI / DLT and DPDP

**Phase 1 — Voice core (the make-or-break phase)**
- Vobiz answer URL, WebSocket serializer and outbound call API.
- Pipecat pipeline: VAD, Smart Turn, Sarvam STT, Gemini, Sarvam TTS.
- Barge-in with `clearAudio`, Indic sentence splitter, call-length cap, silence handling, recording.
- Latency harness: measure time from caller stop to first audio, per language.
- Done when: a real phone call in Telugu, Hindi and English, with interruptions, feels natural, and the latency numbers are logged.

**Phase 2 — Platform backbone**
- Monorepo, CI, environments, secrets.
- Postgres schema (§4.5) and migrations; Supabase auth (email + Google).
- FastAPI skeleton, account settings, audit log.
- Dashboard shell: routing, auth, layout using the design system you choose.

**Phase 3 — AI employee builder**
- Hire flow: pick channel, language and second language; type or speak the brief (chunked transcription).
- AI follow-up brief questions, then a draft agent (name, role, welcome line, sections, capture fields).
- Script editor: draggable sections, end rules, permanent FAQ section, strictness dial 1–5, pre-call and capture variables.
- **Prompt compiler:** script bundle into the system prompt and tools. Order: script = content, rules = conduct, voice = delivery.
- Voice picker with tiers, preview, speed, ambience mixer with volume, auto avatar.
- Test call to your own phone, browser web call, text chat sandbox.
- Lifecycle: Draft → Training → Live → Paused. Publish gate, keep 3 versions, restore, switch mode, start over.

**Phase 4 — Instant channel**
- Per-employee intake URL plus secret, rotate and reveal, intake log (accepted / deduplicated / rejected), test lead.
- Dialer: dial delay, calling window, out-of-window rule (next window / +3h / +6h / next day / hold), retry ladder up to 10 attempts.
- Queue console, redial, one-off call panel.
- Lead sources: website POST, Meta Lead Ads, Google Sheets, Zapier / Pabbly / n8n guides.

**Phase 5 — Post-call intelligence and data views**
- Post-call job: transcript, summary, sentiment, outcome, captured fields. Nothing invented when a field is missing.
- Conversations: filters, saved views, CSV export.
- Call detail: recording, transcript, timeline, notes, share summary.
- Leads: one per phone number; table, card and kanban by outcome; notes; export with a field picker.
- Caller memory across calls, with reset.
- Callback scheduling ("call me at 6") across channels.
- Dashboard and Performance: channel split, connect / qualify / conversion, best hour, leaderboard, within-60-s speed.
- Notifications bell, low-balance alert, auto-DNC confirmation.

**Phase 6 — Billing and numbers**
- Wallet ledger in credits (1 credit = ₹1); Razorpay top-up with order, verify and webhook; presets; 50 free credits.
- Per-second metering from pickup; tier rates; AI-use fee; spend caps; block calls at zero balance.
- Statements, transactions, per-employee usage, invoices with GST.
- Number store: Vobiz inventory, quote and purchase.
- KYC: PAN, then Aadhaar via DigiLocker, with the verified holder reused.
- Auto-renew at ₹649, grace emails, release on lapse. One number per employee; extra channels per number.
- Add 140-series / DLT support if the legal opinion requires it.

**Phase 7 — Bulk campaigns**
- Contacts by CSV, paste or manual entry, with column-to-variable mapping and no silent guesses; saved lists.
- Settings: window, days, holidays, concurrency 1–20, skip DNC, retries 1–9 (same run or next day), schedule, recurrence.
- Duplicate skip across campaigns over N days; per-campaign exclusion list; consent attestation.
- Live panel: calling now / callbacks / done / remaining. Controls: pause, resume, retry exhausted, cancel, CSV export.
- Campaign queue on a shared number (oldest first); capacity preview.

**Phase 8 — Inbound**
- Answer on the attached number, 24/7 or within opening hours (closed message, take a message).
- Greetings for new callers and returning leads; recording disclosure.
- Messages / callback tasks with done tick; missed callers with reasons; one auto call-back within hours, never to DNC numbers.
- Daily email summary.
- Transfer to a human: `transfer_number`, `transfer_when`.
- Outbound employees answer their own callbacks with context.

**Phase 9 — In-call actions**
- Google Calendar: connect, check availability, book, test booking.
- Google Sheets: read and write mid-call.
- Custom HTTP API tool: schema, auth, test console.
- WhatsApp send during or after the call via a BSP, with templates.
- All opt-in per employee.

**Phase 10 — Training and knowledge**
- Teach by typing, speaking or photo (OCR via the LLM's vision); each item sorted into fact or rule, reviewed before save.
- Document upload with retrieval only when relevant (embeddings + pgvector).
- Struggle detector on real calls, turned into one-tap teaching suggestions with quotes.

**Phase 11 — Developer platform**
- API keys (create, revoke), versioned public REST API, OpenAPI spec, Postman collection, request log.
- Account webhooks with HMAC signing: `call.completed`, `call.not_connected`, `call.inbound_answered`, `call.inbound_missed`, `lead.created`, `campaign.status_changed`.
- Delivery log, resend, rotate secret, test.
- Per-employee delivery webhooks with triggers: all connected / skip voicemail / voicemail only.

**Phase 12 — Reliability and internal ops**
- Per-leg failover during calls (STT, LLM, TTS) with health scoring; Premium falls back to Value at the Value price.
- Spoken apology and clean hangup on fatal errors; retry outbound later.
- Provider balance and cost tracking; carrier capacity; engine concurrency.
- Admin console: accounts, impersonation with audit, credits adjustments, voice library, prompts, announcements, system health, revenue and margin.

**Phase 13 — Marketing site and help centre**
- Landing page, channels, pricing, compare, alternatives, glossary, blog, legal pages.
- In-app help centre covering every feature, as Outpero does. Our own wording, not copied.

**Phase 14 — Parity QA and launch hardening**
- Feature-by-feature parity checklist against §3.
- Load test concurrent calls; security review (secrets, RLS, signed webhooks, rate limits); backups.
- Native-speaker QA for all 6 languages; beta with real businesses.

### Stage B — Beat Outpero and other players

From gaps in Outpero and features at Retell and Vapi (S13, S14). These are recommendations, ranked by value:

1. **DNC on Instant calls.** Outpero admits this gap.
2. **Warm transfer.** Brief the human before connecting. Retell has it; Outpero only has a transfer number.
3. **Live call monitoring.** Listen in, whisper, take over (Retell).
4. **Simulation testing.** AI test callers in each Indian language, graded test cases, run automatically before every publish (Retell, Vapi).
5. **A/B testing of scripts and voices on live traffic** (Retell).
6. **AI QA score on every call:** script adherence, mistakes, compliance flags (Retell).
7. **Voicemail detection with a voicemail message; IVR / DTMF navigation** (Retell).
8. **Multi-agent handoff.** For example a language-specialist or closer agent, with context carried over (Vapi Squads).
9. **WhatsApp chat agent sharing the same brain and lead record**, and website voice widget and web calls. Ringg has gone omnichannel (S15).
10. **Native CRM sync:** LeadSquared, Zoho, HubSpot, Salesforce. Outpero relies on webhooks.
11. **Team seats and roles, agency sub-accounts and white-label.** Outpero runs an agency service but no reseller platform.
12. **UPI payment collection on call** via a WhatsApp payment link, with status sent back to the lead.
13. **Missed-call campaigns.** A missed call to your number triggers an instant AI call-back. Very common pattern in India.
14. **Consent ledger and DPDP toolkit:** exportable consent proof, retention policies, PII redaction in transcripts.
15. **Lead scoring and best-time-to-call prediction**, from call history.
16. **Business-owner voice clone,** with recorded consent, on the Premium tier.
17. **Config-as-code, CLI and MCP server** so AI tools can manage agents (Vapi).
18. **Indian holiday calendar built in; festival-aware greetings.**

### Stage C — Language expansion

1. First set: English, Telugu, Hindi, Tamil, Malayalam, Odia. Tiers per §5, with Odia premium pending.
2. Next set, the same providers already cover: Kannada, Marathi, Bengali, Gujarati, Punjabi.
3. Then other Saaras speech-to-text languages, once a voice provider covers them.
4. Gate for each new language: native-speaker test pass on transcription accuracy, naturalness, code-mixing and number/date reading. Publish `language_scores` per voice, as Outpero does.

---

## 8. Open questions and risks

- **TRAI 140-series vs 10-digit numbers** for lead calls: needs a legal opinion before launch (high risk).
- **Vobiz:** official API reference not found; field names come from Sarvam's guide and community docs. KYC sub-account API and per-minute rates also not found. Get both from Vobiz directly.
- **Vobiz serializer** built on Pipecat's Plivo one: untested.
- **Phone-audio quality:** Indian-language transcription and voice quality on 8 kHz phone audio is untested for every provider.
- **Odia premium voice:** unconfirmed.
- **Cost per minute:** LLM and phone costs not measured; tier margins unverified.
- **Data model:** §4.5 is reconstructed from field names; Outpero's real schema is not visible.
- **Legal line:** match features only. Don't copy Outpero's code, prompts, help-centre text or brand.

---

## 9. Sources

| ID | Source | Tier |
|---|---|---|
| S1 | Outpero public app bundle and chunks — https://app.outpero.com/assets/ (read 2026-10-24) | T1 primary artefact |
| S2 | Outpero in-app help centre — https://docs.outpero.com | T1 official docs |
| S3 | Sarvam, "Build a Voice Agent using Vobiz" — https://docs.sarvam.ai/api/integration/build-voice-agent-with-vobiz | T1 |
| S4 | Vobiz agent skills (voice XML, audio streams) — https://www.skills.sh/vobiz-ai/agent-skills/vobiz-audio-streams ; Dograh Vobiz guide — https://docs.dograh.com/integrations/telephony/vobiz | T3 |
| S5 | Pipecat serializers — https://docs.pipecat.ai/server/services/serializers/introduction | T1 |
| S6 | Smart Turn v3 — https://huggingface.co/pipecat-ai/smart-turn-v3 ; https://docs.pipecat.ai/server/utilities/turn-detection/smart-turn-overview | T1 |
| S7 | Sarvam models (Saaras, Bulbul) — https://docs.sarvam.ai/api-reference-docs/getting-started/models | T1 |
| S8 | Cartesia languages — https://docs.cartesia.ai/build-with-cartesia/tts-models/latest ; Sonic-3.6 summary — https://www.plushcap.com/content/cartesia/blog/cartesia-introducing-sonic-36 | T1 / T3 |
| S9 | Smallest Lightning and Pulse — https://docs.smallest.ai/waves/documentation/getting-started/models | T1 |
| S10 | TRAI press release No. 11 of 2025 — https://cms.trai.gov.in/sites/default/files/2025-02/PR_No.11of2025.pdf | T1 |
| S11 | TRAI 1600/140 clarification (Telangana Today) — https://telanganatoday.com/trai-clarifies-rules-for-1600-and-140-number-series-to-prevent-misinformation ; JSA TCCCPR note — https://www.jsalaw.com/wp-content/uploads/2025/02/JSA-Prism-Telecommunications_February-2025_TCCCPR-amendments.Final_.pdf | T2 |
| S12 | DPDP Rules 2025 (AZB) — https://www.azbpartners.com/bank/update-indias-digital-personal-data-protection-framework-comes-into-effect/ ; SCC Online — https://www.scconline.com/blog/post/2025/12/26/digital-personal-data-protection-rules-2025-key-highlights/ | T2 |
| S13 | Retell docs — https://docs.retellai.com/general/introduction | T1 |
| S14 | Vapi docs — https://docs.vapi.ai/quickstart/introduction | T1 |
| S15 | Ringg AI Series A (YourStory) — https://yourstory.com/2026/08/voice-ai-startup-ringg-ai-raises-10m-series-a-peak-xv-partners | T2 |
