# Wiring checklist — keys and accounts

Filled in after the code is built (Track 3). Keys go into `.env` locally or the host's secret store, **never into git**. Each phase's "keys" gates run once its keys are in place. Env var names are fixed by B0 and listed in `.env.example`.

| # | Item | Unlocks | Needed for | Owner | Status |
|---|---|---|---|---|---|
| 1 | Registered company + GST | Razorpay, Vobiz KYC, DLT, invoices | B7, launch | Owner | todo |
| 2 | Legal opinion: TRAI number series for lead calls; DPDP | Dialer rule-table defaults, privacy policy | B7, launch | Owner | todo |
| 3 | Domain + Cloudflare (DNS, R2, Turnstile) | Public URLs for Vobiz, recordings, signup protection | B2, B6, hosting | Owner, then Claude | todo |
| 4 | Vobiz: auth id + token, numbers, KYC sub-account access, 140-series availability | All calls, number store | B2, B5, B7–B9 | Owner | todo |
| 5 | Sarvam API key | Speech-to-text (Saaras), Value voices (Bulbul), optional LLM | B2, B3 | Owner, then Claude | todo |
| 6 | Gemini API key | LLM | B2–B4, B6, B11 | Owner, then Claude | todo |
| 7 | Smallest API key | Standard voices, backup speech-to-text | B3, B13 | Owner, then Claude | todo |
| 8 | Cartesia API key | Premium voices | B3 | Owner, then Claude | todo |
| 9 | Razorpay key id, secret, webhook secret | Credit top-ups | B7 | Owner | todo |
| 10 | Transactional email provider key | Low-balance, summaries, alerts | B6, B9 | Claude | todo |
| 11 | Google Cloud OAuth client (verified app) | Calendar, Sheets | B5, B10 | Owner, then Claude | todo |
| 12 | Meta developer app (Lead Ads webhook) | Instant leads from ads | B5 | Owner, then Claude | todo. V1: page tokens are entered by hand per lead form; the Meta OAuth connect flow is built in Track 3 |
| 13 | WhatsApp BSP (Interakt or AiSensy) + approved templates | WhatsApp actions | B10 | Owner | todo |
| 14 | Strix: `STRIX_LLM` + `LLM_API_KEY`, Docker image (~5.8 GB) | Security test | SEC | Owner | todo |
| 15 | Hosting account (India region) | Deployment | Launch | Owner, then Claude | todo |
| 16 | Test phones + native Telugu and Hindi speakers | Quality checks | B2, B14 | Owner | todo |
| 17 | Five licensed background-sound loops (Office, Call Center, Restaurant, Quiet Room, Retail Store), mono 16 kHz WAV, named `office.wav` etc. in `AXON_AMBIENCE_DIR` | Ambience setting on employees (otherwise calls play no background sound) | B4 | Owner | todo |
| 18 | Public https URLs for the API and the engine (`AXON_API_PUBLIC_URL`, `AXON_ENGINE_PUBLIC_URL`; a tunnel locally) | Vobiz call-end callbacks and answer URL | B2, B5 | Owner, then Claude | todo |
| 19 | Meta app id (`META_APP_ID`) with `META_APP_SECRET`, `META_VERIFY_TOKEN`, a page access token per lead form, `leads_retrieval` permission | Meta Lead Ads into Instant | B5 | Owner, then Claude | todo |
| 20 | Real Vobiz call-end callback and CDR check: confirm the callback payload/format and the `/cdr/{uuid}` fields against one live call | Dialer outcomes (busy, no answer, answered) | B5 | Claude | todo |
| 21 | Vobiz KYC holder API: confirm the paths and bodies the adapter uses (`/kyc/pan`, `/kyc/digilocker/initiate`, `/kyc/digilocker/verify`) with Vobiz; they are not in its public docs | Number KYC (PAN, DigiLocker) | B7 | Owner (ask Vobiz), then Claude | todo |
| 22 | Vobiz number store: confirm the response bodies of `GET /inventory/numbers`, `POST /numbers/purchase-from-inventory` and `DELETE /numbers/{e164}` (paths are documented, bodies are not) and the real 140 and 1600 inventory | Number search, purchase, release | B7 | Claude | todo |
| 23 | Razorpay test-mode keys, and a webhook pointed at `{API URL}/webhooks/razorpay` for `payment.captured` and `order.paid`. A payment is credited only once Razorpay reports it captured (the API reads `GET /payments/{id}`); with manual capture the credit arrives on the webhook | Credit top-ups, contract tests | B7 | Owner, then Claude | todo |
| 24 | Resend domain verified and `EMAIL_FROM` on it | Low-balance, grace and release emails | B7 | Owner, then Claude | todo |
| 25 | Business settings for prices and tax: confirm the launch prices (₹3.5 / ₹5 / ₹7 per minute, ₹0.2 AI fee, ₹649 a month, 50 free credits), the GST rate and service code, and the seller name, GSTIN, address and state in `.env` (`AXON_RATE_*`, `AXON_GST_*`, `AXON_SELLER_*`) | Billing, GST invoices | B7, launch | Owner | todo |
| 26 | Confirm on a real call that Vobiz reads `<Speak>` XML in `en-IN` for the owner-phone code | Owner phone verification | B7 | Claude | todo |
