# Parity checklist — Outpero features to match

Source: `docs/research/` (Outpero's public help centre and public app code). Behaviour only; never copy their text or code.
Each row is ticked by the builder of the phase in brackets, and confirmed by that phase's reviewer.

## Agent ("AI employee") builder [B4]
- [x] Create an employee: pick channel (Instant / Bulk / Inbound), opening language plus an optional second language (English always on)
- [x] Brief by typing or by voice (chunked transcription); AI asks follow-up brief questions
- [x] AI drafts name, role, welcome line, multi-section call flow, capture fields
- [x] Script editor: welcome message, sections (reorder, edit, delete), end-of-call rules, permanent FAQ section that can't be removed
- [x] Script strictness dial 1–5
- [x] Pre-call variables (from webhook or CSV) and captured variables (extracted live) — both declared and prompted (B4), lead values filled and fenced (B5), captured values extracted after each call (B6), CSV values for Bulk fill the script (B8); B10: live use during the call, where the AI passes what it has just learned to a tool (a sheet row, an HTTP body, a booking)
- [x] Precedence: script = content, rules = conduct, voice = delivery only
- [x] Voice tiers Value / Standard / Premium, voice picker with preview, speed, ambience (Office, Call Center, Restaurant, Quiet Room, Retail Store) with volume, auto avatar — B4: tiers, picker, preview, speed, placeholder avatar, ambience setting and mixer hook; the five ambience sound files are licensed assets, listed under "Outside the backend"
- [x] Free test call to the owner's phone, browser web call, text chat sandbox — B4: web call and chat sandbox; B7: the phone test call rings only the owner's phone, proved by a one-time code, and goes through the do-not-call list and the dial rule table
- [x] Lifecycle draft, training, live, paused; live needs a number + switched on + published
- [x] Publish gate ("Apply to live calls") for script, action and webhook edits; voice, capture and training apply instantly; discard pending edits — B4 part done: script publish gate, voice and capture instant, discard; B10: actions go through the publish gate with the script; B11: training applies instantly; B12: the employee's result webhook is part of the script bundle, so it is publish-gated with versions and restore
- [x] Keep the last 3 published versions; restore any
- [x] Switch channel (clears call history, offers a rewrite); start over (wipes script, training, history)
- [x] Duplicate employee
- [x] Toggles: style pack, power prompting, AI-acknowledgement disclosure

## Instant [B5]
- [x] Private intake URL per employee, `X-…-Lead-Secret` header, reveal and rotate secret
- [x] Lead fields mapped to pre-call variables; unknown fields ignored
- [x] Intake log: accepted / deduplicated / rejected; test lead without a real call
- [x] Dial delay; calling window (hard limit 6 AM–10 PM); out-of-window rule: next window / +3h / +6h / next day / hold
- [x] Retry ladder, up to 9 steps (10 attempts total)
- [x] Queue console; redial; one-off call to any number
- [x] Lead sources: website POST, Meta Lead Ads, Google Sheets, Zapier / Pabbly / n8n guides

## Bulk [B8]
- [x] Contacts by CSV, paste or manual entry; column-to-variable mapping with no silent guessing; saved contact lists
- [x] Calling window (hard limit 9 AM–9 PM), weekdays, holiday dates
- [x] Concurrency 1–20; skip-DNC toggle (checked at upload and before every dial) — a person who asked not to be called is skipped whatever the toggle says
- [x] Retries 1–9, same run or next day (0 turns retries off)
- [x] Schedule for later; daily or weekly recurrence
- [x] Cross-campaign dedupe window (N days); per-campaign exclusion list; consent attestation recorded
- [x] Live panel (calling now, callbacks, done, remaining); pause, resume, retry exhausted, cancel, cancel callbacks, restore not-called, per-contact call-now, cancel and retry; CSV export
- [x] Campaigns queue on a shared number, oldest first; capacity preview; campaign analytics

## Inbound [B9]
- [x] Answer the attached number 24/7 or within opening hours (closed message, take a message)
- [x] Greetings for new callers and returning leads; recording disclosure before the greeting; business name from settings
- [x] Messages and callback tasks with a done tick; callback at the requested time within hours
- [x] Missed callers with plain-language reasons; one auto call-back within hours, never to DNC
- [x] Daily email summary of yesterday's calls
- [x] Transfer to a human (transfer number + condition)
- [x] Instant and Bulk employees answer their own leads' call-backs with context (toggle)
- [x] Concurrent callers limited by the number's channels

## Post-call and data [B6]
- [x] Recording, transcript, summary, sentiment, outcome, captured fields; nothing invented when a field is missing
- [x] Conversations: all calls; filters (outcome, sentiment, employee, source, campaign, direction, date, duration, credits); remembered filters; CSV export
- [x] Call detail: timeline, notes, share summary
- [x] Leads: one per phone number across channels; table, card and kanban by outcome; notes; export with a field picker
- [x] Caller memory across calls (toggle, reset)
- [x] "Call me at 6" callback scheduling across channels
- [x] Dashboard and performance: channel split, connect / qualify / conversion %, best hour, leaderboard, within-60-s speed, 7/30/90-day and custom ranges
- [x] Notifications (bell), auto-DNC confirmation, announcements — B6: bell, unread count, mark read, callback and auto-DNC confirmations; B7: low-balance bell entry; B13: announcements from the admin console reach every account's bell

## Billing and numbers [B7]
- [x] Prepaid credits, 1 credit = ₹1, never expire, 50 free credits; top-up presets or custom amount by card or UPI
- [x] Billing from pickup only (ringing, busy and no-answer are free); per-second metering; tier rates; AI-use fee; hourly spend cap
- [x] Low-balance email (about ₹50, at most once a day) and a warning on the credit chip
- [x] Statements (this month and last), transactions with running balance, per-employee usage, invoices with GST
- [x] Number store: search inventory, quote, purchase; first-number KYC by PAN, then Aadhaar via DigiLocker; verified holder reused
- [x] ₹649/month auto-renew from credits; grace period with emails; release on lapse; nothing else deleted
- [x] One number per employee; extra channels per number
- [x] Number types (regular / 140 / 1600) and the purpose rule table (our addition, see DECISIONS)

## In-call actions [B10]
- [x] Google Calendar: connect, availability, book, test booking
- [x] Google Sheets read and write mid-call
- [x] Custom HTTP API tool with a test console
- [x] WhatsApp message during or after a call (the AI sends the template before it ends the call; no separate post-call trigger, see docs/phases/b10.md)
- [x] Every action is opt-in per employee

## Training and knowledge [B11]
- [x] Teach by text, voice or photo; each item becomes a fact or a rule; reviewed before saving
- [x] Documents retrieved only when relevant
- [x] Struggle detector on real calls, turned into one-tap suggestions quoting the call

## Developer platform [B12]
- [x] API keys (create, revoke); public REST API; OpenAPI spec; Postman collection; request log; API status — B12: `/developer/keys`, `/v1/*` (read account, employees, calls, leads, campaigns; post a lead), `/v1/openapi.json`, `/v1/postman.json`, `/developer/requests`, `/developer/status`
- [x] Signed account webhooks: call.completed, call.not_connected, call.inbound_answered, call.inbound_missed, lead.created, campaign.status_changed; delivery log, resend, rotate secret, test — B12: `/developer/webhooks`, `/developer/deliveries`
- [x] Per-employee result webhook with a trigger: all connected / skip voicemail / voicemail only; test payload — B12: `/employees/{id}/webhook`, voicemail comes from the post-call analysis

## Reliability, settings, admin [B13]
- [x] Per-leg failover (STT, LLM, TTS) mid-call; Premium falls back to Value at the Value price, never the other way — B13: every leg holds every vendor that can serve it, unhealthy ones last; a call is billed at the cheapest tier it used
- [x] If nothing is healthy, don't start the call and retry later; on a fatal mid-call error, a spoken apology and clean hangup — B13: health scored from real calls and dials; Instant, campaigns and inbound wait; the Telugu and Hindi apology await the native-speaker check
- [x] Max call length (default 10 min, 10 s – 60 min) — B13: account setting, reaches every call
- [x] Account DNC list (single and bulk add, with reason); auto-add when a caller asks — B6: auto-add; B13: list, search, single and bulk add, owner-only removal
- [x] Settings: business name, caller memory, password, export leads — B6: caller memory, export; B13: name, business name, call length, password change that signs out older sessions
- [x] Admin: accounts, logged impersonation, credit adjustments, voice library, provider health / costs / balances, carrier capacity, system health, revenue, announcements, alerts — B13 (APIs; the console UI is Track 2); costs and balances need staff-entered rates
- [x] Support chat, feedback, rating — B13 (APIs; staff answer from the admin inbox)
- [x] Terms of service acceptance recorded per account: version, time and who — B14: `GET/POST /account/terms`, owner only, never in a support session; the terms text and its version are the owner's (legal)

## Outside the backend (not counted in the 100%)

Each of these needs an owner-supplied asset or Track 2 content, not backend code.

- [ ] The five licensed ambience loops (Office, Call Center, Restaurant, Quiet Room, Retail Store) — WIRING_CHECKLIST #17; the mixer and the setting are built (B4)
- [ ] n8n, Make and Zapier guides — help-centre content (Track 2); the API, spec and webhooks they use are built (B12)
- [ ] The admin console and the whole dashboard UI — Track 2; every API behind them is built (B13)
