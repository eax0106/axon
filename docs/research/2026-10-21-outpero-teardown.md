# Outpero — teardown and rebuild plan

Date: 2026-10-21 · Method: public website, public in-app help centre, publicly served JS bundle and HTTP headers, vendor docs. No login, no private endpoints, no code copied.

## 1. Summary (plain language)

Outpero (outpero.com) sells "AI employees": phone voice agents for Indian SMBs. An agent calls new leads within seconds, runs bulk call lists, or answers inbound calls as a receptionist, in Telugu, Hindi, Tamil, Kannada, Malayalam, Marathi and English. Billing is prepaid credits (1 credit = ₹1), ₹3.5 / ₹5 / ₹7 per talk-minute by voice tier, plus ₹649/month per phone number. It is a product of OpenDG Pvt Ltd, Hyderabad, which also runs a done-for-you automation agency on the same domain.

Under the hood it is a thin, well-polished layer over rented parts: Vobiz (Indian SIP/numbers + KYC), Sarvam (Indian STT + TTS), Smallest / Soniox / Cartesia / Inworld (TTS tiers), Google Gemini 2.5 Flash (LLM), Supabase (auth/DB), Razorpay (payments), Cloudflare R2 (recordings). The engine config fields match the open-source Bolna voice-agent framework. **Inference:** their moat is not tech; it is India-specific packaging — Indian languages, ₹ pricing, number KYC done in-app, DLT/DND compliance, WhatsApp, and a "describe the job, we draft the agent" onboarding.

You can build the same thing. The hard parts are telephony + KYC in India, latency tuning in Indian languages, and compliance — not the dashboard.

---

## 2. Findings (sourced)

Tags: `verified` = 2+ independent sources · `single-source` · `inference` = my reasoning.
Source IDs map to §8.

### 2.1 Company

| Fact | Tag | Src |
|---|---|---|
| Brand "Outpero", HQ Hyderabad, focus Telugu + English, AP/Telangana | single-source | S1 |
| Product of OpenDG Pvt Ltd (opendg.org) | single-source | S2 |
| Also runs an agency arm: "Revenue Capture" from ₹60k, "Ops Efficiency" from ₹1L, "Web Capture" from ₹50k, 19 solutions from ₹14,999 | single-source | S2 |
| Listed in Sarvam AI and Cartesia startup programs | single-source | S1 |
| Founders, funding, revenue, team size | **not found** | — |

### 2.2 Product — the "AI employee" model

Each employee = name + phone number + script + voice + memory. One employee does exactly one job (S3, `single-source`, official help centre):

| Channel | What it does |
|---|---|
| **Instant** | Calls a new lead seconds after it arrives. Private intake URL per employee: `POST https://api.outpero.com/lead-intake/<connection-id>` with header `X-Outpero-Lead-Secret`. JSON fields matching script variables flow into the script. |
| **Bulk** | Calls an uploaded list (CSV/paste/manual). Saved contact lists, scheduling, daily/weekly recurrence. |
| **Inbound** | 24/7 receptionist on the business number: answers, books, answers FAQs, takes messages. |

Every outbound employee also answers its own callbacks with context of the earlier call.

**Lifecycle (S3):** Draft → Training (free, unlimited) → Live (needs number + toggle on + published) → Paused. All three conditions must be true to call.

### 2.3 Full feature inventory

**Onboarding / agent builder** (S3, S4)
- "Employee Store": pick channel + opening language (+ optional 2nd Indian language; English always on).
- Describe the job by typing **or speaking** (voice brief is transcribed). LLM drafts name, role, welcome line, multi-section call flow (qualify → objections → close). API paths seen: `/ai/draft-agent`, `/ai/edit-flow`, `/ai/structure-prompt`, `/ai/voice-prompt`, `/ai/transcribe-chunk`.
- "Swara HR" assistant builds script, voice and capture fields from plain language (S1).
- Industry templates / example prompts (chunk `examplePrompts`).
- Free test call to your own phone; free browser web-call (`WebCallModal`) and text chat sandbox.

**Script** (S3)
- Welcome message + draggable, editable sections + end-call conditions.
- Always-on FAQ section (can't remove).
- **Strictness dial 1–5**: improvise around script ↔ follow wording exactly (e.g. 5 for loan collections).
- Two variable types: **pre-call** (from webhook/CSV, e.g. name, budget) and **captured** (extracted live from conversation, editable post-call).
- Publishing model: script/action/webhook edits need explicit "Apply to live calls"; voice, extraction, training apply instantly. Keeps last 3 published versions, restorable. "Switch channel" and "Start over" (destructive to call history).
- Precedence rule: script = content, rules = conduct, voice = delivery only.

**Training / knowledge** (S3)
- Add knowledge by typing, speaking, or **photographing** a doc (price list, menu). LLM splits into **facts** vs **rules**; user reviews before saving.
- Long docs uploaded as documents, retrieved only when relevant (`inference`: RAG).
- **Auto-coaching**: system flags moments on real calls where the agent struggled/was wrong/dodged and offers one-tap teach suggestions quoting the call.

**Voice — "Swara" engine** (S3, S4)
- Three tiers. Bundle maps tiers to providers: `cartesia/inworld = Premium`, `smallest/soniox = Standard`, `sarvam = Value` (S4).
- Background ambience: Office, Call Center, Restaurant, Quiet Room, Retail Store, each with volume slider.
- Auto-picked avatar matched to voice.
- Premium has a routing toggle: "Auto = Cartesia while plan credits last, then the [Soniox] twin" (S4) — cost control trick.

**In-call actions** (opt-in per employee, S3)
- Book calendar slot live (Google Calendar; cal.com frames allowed in CSP — S5).
- Read/write Google Sheet mid-call.
- Call your own external API mid-call (custom tool).
- Send WhatsApp during/after call (bundle references Interakt, AiSensy, WATI, Gupshup, Meta — S4).

**Post-call** (S3)
- Recording, transcript, summary, sentiment, extracted fields; "nothing fabricated" if missing.
- Per-employee webhook with trigger: all connected calls / skip voicemail / voicemail only; "send test payload" button.
- Account webhooks events (S4): `call.completed`, `call.not_connected`, `call.inbound_answered`, `call.inbound_missed`, `lead.created`, `campaign.status_changed`. Signing secret with rotation.
- Public REST API with API keys, OpenAPI spec, Postman collection, n8n/Make/Zapier guides, API activity log (S4). Gated per account ("not available on this account yet").

**Instant channel controls** (S3)
- Delay before dial (instant or buffer), calling window, out-of-window behaviour (next window / +3h / +6h / next day / hold), retry ladder up to 9 steps (10 attempts).
- Lead sources: website, Meta/Instagram Lead Ads, Google Sheets, Zapier/Pabbly/n8n, any webhook. Intake log shows accepted / deduplicated / rejected. Instant queue console.

**Bulk channel controls** (S3)
- Calling window, weekdays, holiday dates, **concurrency 1–20**, skip-DNC toggle, retries 1–9 (same run or next day), schedule or recurring.
- Cross-campaign dedupe window (skip numbers called in last N days), per-campaign exclusion list.
- Live panel: calling now / scheduled callbacks / done / remaining; pause, resume, retry exhausted, cancel, CSV export. Campaigns queue on a busy number, oldest first.

**Inbound** (S3)
- Opening hours with closed message, missed-caller list with reason, auto call-back to missed callers (once, within hours, never DNC), daily email summary, message/callback tasks. Lines = channels per number; add channels for concurrency.

**Data views** (S3)
- Conversations (every call, heavy filters, CSV export, remembered filters).
- Leads (one row per phone number across channels; table / card / **kanban by outcome**; notes; share summary).
- Performance analytics (channel split, 7/30/90 days, filters).
- Caller memory across calls (toggle, reset) — `/accounts/me/caller-memory`.

**Numbers** (S3)
- Search & buy Indian number in-app; ₹649/month from credits; auto-renew, grace + email retries then release.
- First number needs **PAN + Aadhaar via DigiLocker** consent; holder reused afterwards. Backed by **Vobiz sub-accounts** ("KYC holders (Vobiz sub-accounts)" in admin UI — S4). A second telephony option "voicelink" exists (S4).

**Billing** (S3, S1)
- Prepaid credits 1:1 ₹, Razorpay card/UPI, presets, never expire, 50 free credits.
- Only billed from pickup; ringing/busy/no-answer free. Low-balance email at ~₹50, max once/day.
- Statements, transactions ledger, per-employee cost breakdown, CSV.
- Per-minute: Value ₹3.5 · Standard ₹5 · Premium ₹7 (S1). Volume discounts mentioned.

**Compliance** (S3)
- Hard calling windows enforced server-side: Bulk 9 AM–9 PM, Instant 6 AM–10 PM.
- Consent attestation recorded per campaign/source; cold/scraped lists banned.
- Auto-DNC when caller asks; account DNC list checked at upload and pre-dial (Bulk only; **not yet applied to Instant** — gap they admit).
- "Call is recorded" disclosure before greeting.
- DLT registration claimed (S1).

**Reliability** (S3, S6)
- Max call length default 10 min (10 s–60 min).
- STT, LLM and TTS each fail over to alternate provider mid-call. Premium voice degrades to Value voice at Value price, never the reverse.
- If nothing healthy: call not started, retried later; mid-call failure → spoken apology + clean hangup.
- Containerised, single TLS terminator, agent-creation API + DB + cache on private network (S6).

**Internal ops / admin** (S4 — admin route list in bundle)
- Live calls, carrier capacity planning & reconcile, provider balances, provider costs, provider health (with "llm-primary" switch), FX rate, revenue, secrets, global APIs, engines, premium-voice anchor, voice library, alerts, broadcast notifications, deleted identities, staff impersonation (audited).
- A built-in **sales CRM** (`/admin/sales/leads|autopush|staff|vendors|industries`) — they dogfood outbound sales.

### 2.4 Tech stack (from public headers / bundle)

| Layer | What they use | Tag | Src |
|---|---|---|---|
| Marketing site | Vite SPA on Vercel (bom1) | verified (header + asset path) | S5 |
| Dashboard + docs | React SPA (Vite chunks), Framer Motion, charts lib, behind Cloudflare | verified | S5 |
| Auth / DB / realtime | Supabase (`*.supabase.co` + wss) | verified (CSP + Security page) | S5, S6 |
| Backend API | `api.outpero.com`, FastAPI-style 404 `{"detail":"Not Found"}` | inference | S5 |
| Voice engine | `engine.outpero.com` (+ wss), mirror `engine.viavatsal.in` | single-source | S5 |
| Engine config | groups `transcriber / synthesizer / llm / task`, fields `endpointing`, `buffer_size`, `incremental_delay`, `number_of_words_for_interruption` | single-source | S4 |
| Telephony | Vobiz (SIP, DIDs, KYC sub-accounts); "voicelink" alt | single-source | S4, S8 |
| STT | Sarvam `saaras:v4` default (Soniox seen too) | single-source | S4 |
| LLM | Google `gemini-2.5-flash` default, with failover | single-source | S4, S6 |
| TTS | Sarvam `bulbul:v2/v3`, Smallest, Soniox, Cartesia, Inworld | single-source | S4 |
| Recordings | Cloudflare R2 | verified (CSP + Security page) | S5, S6 |
| Payments | Razorpay | verified | S5, S6 |
| Analytics | PostHog EU, setup flow only | verified | S5, S6 |
| Bot protection | Cloudflare Turnstile | single-source | S5 |
| WhatsApp | Interakt / AiSensy / WATI / Gupshup (BSP options) | single-source | S4 |

Bolna (open-source, MIT, ~800 stars) is a FastAPI + Redis voice-agent orchestrator with `transcriber/synthesizer/llm` blocks, supporting Cartesia and Smallest TTS (S7). Bolna's dashboard exposes "linear delay" and "words before interruption" settings (S9) and lists Vobiz as telephony (S8). **Inference:** Outpero's engine is very likely built on (or modelled on) open-source Bolna. Not confirmed.

### 2.5 Their claims (marketing, T3 — unverified)
"Calls in under 30 s", "99.9% uptime", "up to 85% cheaper than Bland/Vapi/Retell", "setup in 2 min". Competitor prices they quote: Bland/Vapi/Retell ₹12–15/min, Bolna ₹8–10/min (S1). The pricing table labels Value "English only" while also saying "native multilingual" — inconsistency on their own page.

---

## 3. Architecture to rebuild (analysis)

All joints are `inference` unless marked. Built from separate sources; untested as a whole.

```
 Lead sources                      Your platform                                       Vendors
 ───────────                       ─────────────                                       ───────
 Meta Lead Ads ─┐
 Website form ──┤  POST /lead-intake/{id}   ┌──────────────┐
 Sheets/Zapier ─┼─────────────────────────▶ │  API (FastAPI)│── Supabase (auth, Postgres, RLS)
 CSV upload ────┘                           │  + workers    │── Redis queue (dial jobs, retries)
                                            │  scheduler    │── Razorpay (credits)  ── R2 (recordings)
 Dashboard (React SPA) ◀──── REST/wss ────▶ └──────┬───────┘
                                                   │ start call (agent cfg + vars)
                                                   ▼
                                     ┌─────────────────────────────┐
  Phone (PSTN) ◀── SIP/media WS ───▶ │ Voice engine (per call)      │── STT: Sarvam / Soniox (stream)
        ▲                            │ VAD → STT → LLM → TTS loop   │── LLM: Gemini Flash (+ fallback)
        │                            │ interruptions, endpointing   │── TTS: Sarvam/Smallest/Cartesia
     Vobiz SIP trunk / DID           │ tools: calendar, sheet, http,│── WhatsApp BSP, Google APIs
     (numbers + KYC)                 │ WhatsApp, end-call           │
                                     └──────────────┬──────────────┘
                                                    │ call ended
                                                    ▼
                                post-call job: transcript → LLM summary, sentiment,
                                field extraction → DB → webhooks / CRM / Sheets / WhatsApp
                                → "struggle detector" → training suggestions
```

**Joints:**
| From → To | Tag |
|---|---|
| Vobiz SIP ↔ Bolna-style engine | sourced (Bolna lists Vobiz, S8) |
| Bolna ↔ Cartesia / Smallest TTS | sourced (S7) |
| Bolna ↔ Sarvam STT/TTS, Gemini LLM | inference (LiteLLM covers Gemini; Sarvam needs adapter) |
| Engine ↔ Supabase / Razorpay billing per minute | inference |
| Post-call LLM extraction → webhooks | inference (standard pattern) |
| Per-leg mid-call failover | inference — hardest piece; needs testing |

### Build choice (recommendation)

**Recommend: Pipecat (BSD-2) for the engine, not forking Bolna.** Reasons:
1. Pipecat is phone-first over WebSocket and lets you mix any STT/LLM/TTS freely (S10, S11). That is exactly the Indian-provider mix you need.
2. Bolna works and is MIT, but its core supports fewer Indian providers out of the box and is driven by one company's hosted product (S7). You'd be maintaining a fork.
3. LiveKit Agents is better for WebRTC rooms/video; for pure PSTN calls it adds a media server you don't need yet (S10, S11).

Where I'd differ from Outpero: their moat is packaging, so copying their stack 1:1 gives you no edge. Pick a niche (one vertical + one or two languages) and win on quality there.

---

## 4. Unit economics (inference — check before pricing)

Approx cost per connected minute, Value tier:

| Leg | Rate | Per min | Src |
|---|---|---|---|
| STT Sarvam | ₹30/hour | ~₹0.50 | S12 (T1 vendor docs) |
| TTS Sarvam Bulbul | ₹30 / 10k chars | ~₹1.0–1.5 (assumes agent speaks ~350–500 chars/min) | S12 + inference |
| LLM Gemini Flash | per token | ~₹0.1–0.3 | inference, not checked |
| Telephony Vobiz | — | **not found** | — |
| Number | ₹649/mo retail | — | S1 |

So Value ≈ ₹2–2.5/min before telephony vs ₹3.5 price. Margins are thin on Value, better on Standard/Premium. Soniox STT ~$0.12/hour (S13) is far cheaper than Sarvam STT if its Indian-language accuracy holds — test it. Outpero's "Premium → Soniox twin when Cartesia credits run out" toggle shows they actively arbitrage TTS cost.

---

## 5. Build plan (recommendations)

**Phase 0 — prove the call (1–2 weeks)**
1. Vobiz account + one DID; get SIP / media-stream working.
2. Pipecat pipeline: Silero VAD → Sarvam STT (Telugu/Hindi/English) → Gemini Flash → Sarvam Bulbul TTS.
3. Measure: first-response latency (target < 1 s), barge-in, code-switching. This is the make-or-break step.

**Phase 1 — MVP (4–6 weeks)**
1. Supabase schema: accounts, employees, script_versions, knowledge_items, numbers, leads, calls, call_events, campaigns, campaign_contacts, credit_ledger, webhooks, dnc.
2. Agent builder: description → LLM draft (structured JSON: name, welcome, sections, capture fields). Strictness dial = prompt template switch.
3. Instant channel: lead-intake URL + secret, Redis queue, calling window, retry ladder.
4. Post-call: transcript → summary/sentiment/extraction → webhook.
5. Credits via Razorpay; bill per connected second; block calls at zero balance.
6. Compliance baked in server-side: hard hours, recording disclosure, DNC auto-add, consent attestation log.

**Phase 2 — parity**
Bulk campaigns (concurrency, dedupe, scheduling), inbound receptionist, in-call tools (Calendar, Sheets, HTTP, WhatsApp), knowledge docs (RAG), versions/publish, leads kanban, analytics, public API + signed webhooks, in-app number purchase + KYC (via Vobiz sub-accounts / DigiLocker).

**Phase 3 — beat them**
Per-leg provider failover, struggle-detector coaching, caller memory, voice tiers with cost routing, DNC on Instant (their known gap), vertical templates.

---

## 6. Risks and open questions

- **Telephony + KYC in India** is the real gate: TRAI/DLT rules, number ownership KYC, 140-series vs 10-digit numbers for promotional calls. Get legal advice; not researched here in depth.
- **DPDP Act 2023** (data protection): consent + storage of call recordings. Not researched here.
- Vobiz per-minute rates and sub-account KYC API: **not found** publicly.
- Whether Outpero's engine is really Bolna: **unconfirmed** (field-name match only).
- Indian-language STT accuracy (Sarvam vs Soniox vs others) on noisy phone audio: needs your own benchmark.
- Founders, funding, traction of Outpero: **not found**.
- Legal: building a competing product from public info is fine. Don't copy their code, text, prompts, brand, or call their private APIs.

---

## 7. Gates

| Gate | Status |
|---|---|
| Identify the company correctly | met (outpero.com, OpenDG) |
| Full feature inventory | met (from official help centre + bundle) |
| Tech stack per layer | met, mostly single-source |
| Rebuild architecture with labeled joints | met (inference-labelled) |
| Build plan with phases | met |
| Cost model | partial — telephony cost not found |
| Company background (founders, funding) | unmet — not found |

---

## 8. Sources

| ID | Source | Tier | Note |
|---|---|---|---|
| S1 | Outpero homepage — https://www.outpero.com/ (fetched 2026-10-21) | T3 | vendor marketing |
| S2 | Outpero agency page — https://www.outpero.com/agency | T3 | vendor marketing |
| S3 | Outpero help centre (in-app docs, served at https://docs.outpero.com, chunk `Docs-*.js`) | T1 | official product docs |
| S4 | Outpero public app JS bundle — https://app.outpero.com/assets/* | T1 | primary artefact; interpretation is mine |
| S5 | HTTP headers / CSP of www, app, docs.outpero.com | T1 | primary artefact |
| S6 | Outpero "Security & Sub-processors" page (in app bundle) | T1 | official policy |
| S7 | bolna-ai/bolna GitHub — https://github.com/bolna-ai/bolna | T1 | official repo |
| S8 | Bolna × Vobiz integration — https://www.bolna.ai/integrations/vobiz ; Vobiz seed news — https://news.ventureintelligence.com/private-equity/telephony-infra-platform-vobiz-raises-%241-m-led-by-piper-serica | T3 / T2 | |
| S9 | Bolna docs, Transcriber tab — https://docs.bolna.ai/playground/transcriber-tab | T1 | |
| S10 | LiveKit vs Pipecat — https://livekit.io/field-guides/guide/livekit-vs-pipecat | T3 | competitor-written |
| S11 | Plivo × Pipecat — https://www.plivo.com/pipecat/ ; Fora Soft comparison — https://www.forasoft.com/blog/article/pipecat-vs-livekit-agents | T3 | |
| S12 | Sarvam pricing — https://docs.sarvam.ai/api-reference-docs/pricing | T1 | TTS marked beta pricing |
| S13 | Soniox pricing compare — https://soniox.com/compare/stt/pricing (June 2026) | T3 | vendor self-report |
