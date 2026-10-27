# Decisions

Settled decisions. Don't reopen them without the owner. Newest at the bottom.

| Date | Decision | Why |
|---|---|---|
| 2026-10-24 | V1 = Stage A only: a feature-for-feature Outpero rebuild with our own UI and brand. Stages B and C are parked. | Owner wants parity first |
| 2026-10-24 | V1 languages: Telugu, English, Hindi | Smallest useful set; providers cover all three |
| 2026-10-24 | No fake providers. Real adapters ("plugs") per vendor; keys are requested after the code is built | Fakes can't prove call quality; owner supplies keys later |
| 2026-10-24 | Stack: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Postgres 16 + pgvector, Redis + Arq, Pipecat (Silero VAD + Smart Turn v3), React + Vite + TS | See BUILD_PLAN §2 |
| 2026-10-24 | Own auth (argon2 + JWT), not Supabase | No vendor lock; works offline and on any host |
| 2026-10-24 | Must run on macOS, Windows and Linux and deploy to any container host | Owner requirement |
| 2026-10-24 | Phone numbers: support both regular 10-digit and 140-series (promotional), plus 1600-series (service, for eligible customers). Every employee or campaign declares a purpose (promotional / service / transactional). A configurable rule table allows or blocks each purpose and number-type pairing before dialing. Defaults: inbound and call-backs on 10-digit are OK; outbound promotional only on 140-series; Instant lead calls follow the strict or relaxed setting decided by legal. | TRAI Feb 2025 TCCCPR amendment; legal opinion pending |
| 2026-10-24 | Parked open questions: DPDP specifics, call quality on phone lines, Vobiz connector and docs, cost per minute | Owner: revisit later |
| 2026-10-24 | Never copy Outpero code, prompts, text or brand; rebuild from scratch | Legal and quality |
| 2026-10-24 | Skills: unlazy always on in every session; ponytail for all code; thermo-nuclear-code-quality-review is the only review skill; Strix after the backend is complete; frontend by Opus only, no design-workflow skills | Owner decision |
| 2026-10-24 | Session model: Opus orchestrator; Opus builder for B0–B2 and B13, Sonnet (high) for B3–B12 and B14; Opus reviewer per phase | Cost vs. quality |
| 2026-10-24 | Brand: "Axon Voice Engine by ALTERX". Dashboard design language from alterx.co.in | Owner |
| 2026-10-24 | Non-stop autonomous run of B0–B14: orchestrator auto squash-merges after reviewer APPROVE + gates ALL MET; planned dependencies, builds and tests pre-approved; usage-limit auto-continue on | Owner wants the build not to stop until B14 |
| 2026-10-24 | GitHub account havishvardhan04-creator; local-git mode until it has write access to eax0106/axon, then push everything | Both accounts have read-only access today |
| 2026-10-25 | Instant calling window: default 9 AM–9 PM, inside the hard 6 AM–10 PM IST limit (approved). The Instant strict/relaxed setting stays parked pending the legal opinion. | TRAI schedule II bands; owner-proxy decision |
| 2026-10-25 | Calling hours are always fixed IST (UTC+5:30): no account time zone, no tzdata dependency. Revisit only for Stage C / non-India markets. | Every dialable number is Indian; India has no daylight saving; Windows needs tzdata for named zones |
| 2026-10-25 | Meta page access tokens are entered by hand per lead form for V1; the OAuth connect flow is built in Track 3. | Needs a verified Meta app; keeps V1 shippable |
| 2026-10-27 | Billing defaults (B7, for the owner to confirm; all are environment settings): ₹3.5 / ₹5 / ₹7 per talk-minute by voice tier, ₹0.2 per use of AI help, 50 free credits, ₹649 a month per number, 7 days of grace, low-balance warning at ₹50. Prices include GST (a ₹P top-up is P credits; the invoice splits P into taxable value and tax). | Launch figures from the Outpero teardown; the business confirms them |
| 2026-10-27 | The Instant strict / relaxed setting defaults to **strict** (an Instant call is read as an outbound one) until the legal opinion arrives; an admin can relax it. A missing rule row blocks the call. | Fail closed on a legal question |
| 2026-10-27 | Free test calls ring only the owner's own phone, proved by a one-time code spoken to it, and go through do-not-call and the rule table | A free call to any number is a way to ring strangers at our cost |
| 2026-10-27 | A number purchase whose carrier answer is lost (timeout, 5xx) is **not** refunded: the number is kept as `reconcile`, the credits stay held and the owner is told. Only a clear refusal (4xx) refunds. Calls the dialer cannot account for are treated the same way. | The carrier may have sold it; refunding would give a rented number away for free |
| 2026-10-27 | A channel is one call in flight on a number; the dialer holds a call back while all are busy. Raising the count is charged at once for the days left in the period; lowering is free and not refunded. | Otherwise channels cost money and do nothing, and could be raised after a renewal and lowered before the next |
| 2026-10-27 | AI help is paid once per use. A re-analysis is free to ask for (the analysis fee is taken when it completes, once per call) and one chunk of a spoken brief is not charged (the brief pays when it goes to the builder); both still count against the hourly allowance. | A failed analysis delivers nothing; N chunks would charge N fees for one brief |
| 2026-10-27 | A top-up is credited only when Razorpay itself reports the payment captured (a signed checkout alone is not enough); an authorized-only payment waits for the webhook. | With manual capture an authorized payment can be refunded and the credits would stay |

