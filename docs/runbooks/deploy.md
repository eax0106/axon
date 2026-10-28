# Deploy, upgrade, roll back

The same containers run everywhere: `api`, `engine`, `worker` (built from `deploy/Dockerfile`), with Postgres 16 with pgvector, and Redis 7. `deploy/docker-compose.yml` is the development stack; a host replaces the pieces it provides itself.

## Before the first deploy

1. **Network.** Publish only the API and the engine, behind a reverse proxy that does TLS. Do not publish Postgres or Redis (the Compose file publishes them for development with the password `axon`). Give both a private network and real passwords in `DATABASE_URL` and `REDIS_URL`.
2. **Proxy.** Set `FORWARDED_ALLOW_IPS` to the proxy's address. Without it every user looks like the proxy and shares one sign-in limit of 100 tries per 15 minutes. Set the proxy's request body limit at or under 10 MB (the API refuses larger bodies with 413 anyway) and do not log query strings: the live-call WebSocket carries the session token in its URL.
3. **Settings.** Copy `.env.example`; set `AXON_JWT_SECRET` (32+ random characters), `AXON_ENGINE_PUBLIC_URL`, `AXON_API_PUBLIC_URL` (both https, reachable by Vobiz), and each vendor key you have. Leave `AXON_AUTH_RATE_LIMIT` unset: `off` is for load tests.
4. **Region.** An India region (Mumbai or Hyderabad) for Vobiz and Sarvam latency.

## First deploy

```bash
docker compose -f deploy/docker-compose.yml up -d --build --wait    # on a host: your equivalent
uv run python scripts/compose_smoke.py                              # prints COMPOSE HEALTHY
```

The `migrate` service applies every migration and seeds the voice catalog; both are safe to repeat. Then check `GET /readyz` (200 with Postgres and Redis up) and `GET /admin/providers` with a staff token: each vendor shows `configured`, `missing_key` or `unhealthy`.

**Make the first staff admin** (there is no sign-up for staff): sign up as a normal user, then

```sql
UPDATE users SET is_platform_admin = true WHERE email = 'you@example.com';
```

## Upgrade

1. Take a backup first ([backup-restore.md](backup-restore.md)). Migrations only move forward in production.
2. Build and start the new images; `migrate` runs before `api` and `worker` start.
3. Check `GET /readyz`, then `GET /admin/system` (database, Redis, the worker's heartbeat) and `GET /admin/alerts`.

Calls in progress are on the engine: restart `engine` last, when `GET /admin/capacity` shows no calls in flight, or accept that those calls end.

## Roll back

A new image that misbehaves but made no schema change: start the previous image. If the upgrade ran a migration, either keep the new schema (the previous image usually ignores added columns) or restore the backup taken in step 1 into a new database and point `DATABASE_URL` at it. Do not run `alembic downgrade` on production data without a backup and a reason.
