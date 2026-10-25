# Parity checklist — Outpero features to match

Source: `docs/research/` (Outpero's public help centre and public app code). Behaviour only; never copy their text or code.
Each row is ticked by the builder of the phase in brackets, and confirmed by that phase's reviewer.

## Agent ("AI employee") builder [B4]
- [x] Create an employee: pick channel (Instant / Bulk / Inbound), opening language plus an optional second language (English always on)
- [x] Brief by typing or by voice (chunked transcription); AI asks follow-up brief questions
- [x] AI drafts name, role, welcome line, multi-section call flow, capture fields
- [x] Script editor: welcome message, sections (reorder, edit, delete), end-of-call rules, permanent FAQ section that can't be removed
- [x] Script strictness dial 1–5
- [ ] Pre-call variables (from webhook or CSV) and captured variables (extracted live) — done so far: both declared and prompted (B4), lead values filled and fenced (B5), captured values extracted after each call (B6); rest: CSV values for Bulk (B8) and extraction during the call (B10)
- [x] Precedence: script = content, rules = conduct, voice = delivery only
- [ ] Voice tiers Value / Standard / Premium, voice picker with preview, speed, ambience (Office, Call Center, Restaurant, Quiet Room, Retail Store) with volume, auto avatar — B4 part done: tiers, picker, preview, speed, placeholder avatar, ambience setting and mixer hook; rest: the five licensed ambience loops (WIRING_CHECKLIST #17)
- [ ] Free test call to the owner's phone, browser web call, text chat sandbox — B4 part done: web call, chat sandbox, phone test call to any +91 mobile; rest: verify the owner's number and route test calls through DNC and the purpose rule (B7)
- [x] Lifecycle draft, training, live, paused; live needs a number + switched on + published
- [ ] Publish gate ("Apply to live calls") for script, action and webhook edits; voice, capture and training apply instantly; discard pending edits — B4 part done: script publish gate, voice and capture instant, discard; rest: actions B10, training B11, webhooks B12
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
- [ ] Contacts by CSV, paste or manual entry; column-to-variable mapping with no silent guessing; saved contact lists
- [ ] Calling window (hard limit 9 AM–9 PM), weekdays, holiday dates
- [ ] Concurrency 1–20; skip-DNC toggle (checked at upload and before every dial)
- [ ] Retries 1–9, same run or next day
- [ ] Schedule for later; daily or weekly recurrence
- [ ] Cross-campaign dedupe window (N days); per-campaign exclusion list; consent attestation recorded
- [ ] Live panel (calling now, callbacks, done, remaining); pause, resume, retry exhausted, cancel, cancel callbacks, restore not-called, per-contact call-now, cancel and retry; CSV export
- [ ] Campaigns queue on a shared number, oldest first; capacity preview; campaign analytics

## Inbound [B9]
- [ ] Answer the attached number 24/7 or within opening hours (closed message, take a message)
- [ ] Greetings for new callers and returning leads; recording disclosure before the greeting; business name from settings
- [ ] Messages and callback tasks with a done tick; callback at the requested time within hours
- [ ] Missed callers with plain-language reasons; one auto call-back within hours, never to DNC
- [ ] Daily email summary of yesterday's calls
- [ ] Transfer to a human (transfer number + condition)
- [ ] Instant and Bulk employees answer their own leads' call-backs with context (toggle)
- [ ] Concurrent callers limited by the number's channels

## Post-call and data [B6]
- [x] Recording, transcript, summary, sentiment, outcome, captured fields; nothing invented when a field is missing
- [x] Conversations: all calls; filters (outcome, sentiment, employee, source, campaign, direction, date, duration, credits); remembered filters; CSV export
- [x] Call detail: timeline, notes, share summary
- [x] Leads: one per phone number across channels; table, card and kanban by outcome; notes; export with a field picker
- [x] Caller memory across calls (toggle, reset)
- [x] "Call me at 6" callback scheduling across channels
- [x] Dashboard and performance: channel split, connect / qualify / conversion %, best hour, leaderboard, within-60-s speed, 7/30/90-day and custom ranges
- [ ] Notifications (bell), auto-DNC confirmation, announcements — B6 part done: bell, unread count, mark read, callback and auto-DNC confirmations; rest: announcements (admin console, B13), low-balance alert (B7)

## Billing and numbers [B7]
- [ ] Prepaid credits, 1 credit = ₹1, never expire, 50 free credits; top-up presets or custom amount by card or UPI
- [ ] Billing from pickup only (ringing, busy and no-answer are free); per-second metering; tier rates; AI-use fee; hourly spend cap
- [ ] Low-balance email (about ₹50, at most once a day) and a warning on the credit chip
- [ ] Statements (this month and last), transactions with running balance, per-employee usage, invoices with GST
- [ ] Number store: search inventory, quote, purchase; first-number KYC by PAN, then Aadhaar via DigiLocker; verified holder reused
- [ ] ₹649/month auto-renew from credits; grace period with emails; release on lapse; nothing else deleted
- [ ] One number per employee; extra channels per number
- [ ] Number types (regular / 140 / 1600) and the purpose rule table (our addition, see DECISIONS)

## In-call actions [B10]
- [ ] Google Calendar: connect, availability, book, test booking
- [ ] Google Sheets read and write mid-call
- [ ] Custom HTTP API tool with a test console
- [ ] WhatsApp message during or after a call
- [ ] Every action is opt-in per employee

## Training and knowledge [B11]
- [ ] Teach by text, voice or photo; each item becomes a fact or a rule; reviewed before saving
- [ ] Documents retrieved only when relevant
- [ ] Struggle detector on real calls, turned into one-tap suggestions quoting the call

## Developer platform [B12]
- [ ] API keys (create, revoke); public REST API; OpenAPI spec; Postman collection; request log; API status
- [ ] Signed account webhooks: call.completed, call.not_connected, call.inbound_answered, call.inbound_missed, lead.created, campaign.status_changed; delivery log, resend, rotate secret, test
- [ ] Per-employee result webhook with a trigger: all connected / skip voicemail / voicemail only; test payload
- [ ] n8n, Make and Zapier guides

## Reliability, settings, admin [B13]
- [ ] Per-leg failover (STT, LLM, TTS) mid-call; Premium falls back to Value at the Value price, never the other way
- [ ] If nothing is healthy, don't start the call and retry later; on a fatal mid-call error, a spoken apology and clean hangup
- [ ] Max call length (default 10 min, 10 s – 60 min)
- [ ] Account DNC list (single and bulk add, with reason); auto-add when a caller asks
- [ ] Settings: business name, caller memory, password, export leads
- [ ] Admin: accounts, logged impersonation, credit adjustments, voice library, provider health / costs / balances, carrier capacity, system health, revenue, announcements, alerts
- [ ] Support chat, feedback, rating
