# Capacity

Two limits matter: how many calls the voice engines carry at once, and how many requests the API and database carry.

## Calls at once

`AXON_MAX_CONCURRENT_CALLS` (default 100) is the platform-wide cap. Above it new calls wait (an Instant call without using an attempt; a campaign with a note; an incoming caller is recorded as missed and called back). **100 is a first guess, not a measurement.** It cannot be measured without vendors: every call runs speech-to-text, the language model and text-to-speech, and those need the keys in `docs/WIRING_CHECKLIST.md`. Measure it at wiring (WIRING_CHECKLIST #31):

1. Deploy one `engine` on the host you will use. Put test calls through it with `scripts/load_test.py` running alongside to prove the API stays responsive, and place real calls in steps (5, 10, 20, 40, ...). Use a Vobiz test number and your own phones, or a second Vobiz account as the callee.
2. At each step watch, on the engine host: CPU (a call is mostly waiting on vendors; the Silero VAD and Smart Turn models are the CPU part), memory per call, and the reply delay: the gap between `user_stopped_speaking` and `bot_started_speaking` in each call's stored events (the target is replies under 1 s).
3. The safe cap per engine is the step before CPU passes about 70% or reply delay starts to grow. Set `AXON_MAX_CONCURRENT_CALLS` to the sum over your engines, minus a margin for failover.
4. Vendor rate limits count too: ask Sarvam, Gemini, Smallest and Cartesia for their concurrent-session limits; the cap must stay under the lowest of them. And Vobiz's channels per number bound inbound calls.

## API and database

Run the load test against a server with `AXON_AUTH_RATE_LIMIT=off` (otherwise the sign-up limit refuses it, and the script says so):

```bash
uv run python scripts/load_test.py --base-url http://localhost:8000 --users 50 --rounds 20 --max-p95-ms 1000
```

It signs up and signs in that many users at once, then each reads ten dashboard routes, and prints p50, p95 and p99 per route and the error count; it exits 1 on any error or a slow read route.

**Measured in B14, on a 4-core shared sandbox** (load generator, 4 uvicorn workers, Postgres and Redis all on the same four cores, so these are floors, not production figures): 50 users, 12,000 requests: 0 errors, reads p50 about 80 ms, p95 about 650 to 850 ms; 200 users, about 24,000 requests: 0 errors, reads p50 about 550 ms, p95 about 3 s, sign-up p95 about 20 s (argon2 hashing is CPU-bound by design). Re-run it on the real host; there the engines and the load generator are on other machines.

Sizing rules that follow:

- **Hashing is the CPU spike.** Sign-up and sign-in each cost one argon2 hash (tens of milliseconds of one core, 64 MB). They run in threads so they never stall other requests, but a burst of sign-ins needs cores: run at least as many `api` workers as cores, `uvicorn ... --workers N`.
- **Database connections.** Each `api` worker holds up to 15 pooled connections (SQLAlchemy defaults: 5 plus 10 overflow), each `engine` and `worker` process up to 15 more. Keep the sum under Postgres `max_connections` (100 by default), or put PgBouncer in front.
- **Opening a connection** may take up to 15 s before the request fails (the readiness probe has its own 2 s limit), so a busy host slows requests instead of failing them.
- **Redis** carries live events, queues and rate limit counters: small, one instance is plenty.
