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
