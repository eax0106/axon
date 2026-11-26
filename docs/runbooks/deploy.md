# Deploy, upgrade, roll back

The same containers run everywhere: `api`, `engine`, `worker` (built from `deploy/Dockerfile`), with Postgres 16 with pgvector, and Redis 7. `deploy/docker-compose.yml` is the development stack; a host replaces the pieces it provides itself.

## Before the first deploy

1. **Network.** Publish only the API and the engine, behind a reverse proxy that does TLS. Do not publish Postgres or Redis (the Compose file publishes them for development with the password `axon`). Give both a private network and real passwords in `DATABASE_URL` and `REDIS_URL`.
2. **Proxy.** Set `FORWARDED_ALLOW_IPS` to the proxy's address. Without it every user looks like the proxy and shares one sign-in limit of 100 tries per 15 minutes. Set the proxy's request body limit at or under 10 MB (the API refuses larger bodies with 413 anyway) and do not log query strings: the live-call WebSocket carries the session token in its URL.
3. **Settings.** Copy `.env.example`; set `AXON_JWT_SECRET` (32+ random characters), `AXON_SECRETS_KEY` (`uv run python -m app.secretbox new-key`; the API, worker and migration refuse to run without it, and losing it loses every stored secret, so keep a copy outside the host), `AXON_ENGINE_PUBLIC_URL`, `AXON_API_PUBLIC_URL` (both https, reachable by Vobiz), and each vendor key you have. Leave `AXON_AUTH_RATE_LIMIT` unset: `off` is for load tests.
4. **Region.** An India region (Mumbai or Hyderabad) for Vobiz and Sarvam latency.

## One VM in Mumbai (the chosen setup)

One Linux VM runs the whole stack with `deploy/docker-compose.prod.yml` on top of the development file. Only Caddy is published, on ports 80 and 443, and it gets the TLS certificates itself. Postgres, Redis, the API, the engine and the web server stay on Compose's private network, Postgres and Redis get real passwords, every service restarts on failure and after a reboot, logs are capped at 100 MB per service, and a `backup` service writes a dump a day to `deploy/backups` (14 kept).

1. **VM.** Ubuntu 24.04 LTS in Mumbai (AWS Lightsail or EC2 `ap-south-1`, or DigitalOcean `blr1`), at least 4 vCPU and 8 GB of memory to start; the call count it carries is measured in [capacity.md](capacity.md). Open only ports 22, 80 and 443 in its firewall, and allow SSH by key only.
2. **DNS.** Two names pointing at the VM's public address, for example `app.example.in` (dashboard and API) and `voice.example.in` (engine). Caddy cannot get certificates until both resolve.
3. **Docker.** Install Docker Engine and the Compose plugin from docker.com's apt repository.
4. **Code and settings.** Clone the repository, copy `.env.example` to `.env`, and set:
   - `AXON_JWT_SECRET`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD` (long random strings; the Postgres password only takes effect when the database is first created);
   - `AXON_SECRETS_KEY` (made as in step 3 above; keep a copy off the VM);
   - `AXON_APP_DOMAIN`, `AXON_ENGINE_DOMAIN`, `AXON_ACME_EMAIL`;
   - `AXON_API_PUBLIC_URL=https://<app domain>/api` and `AXON_ENGINE_PUBLIC_URL=https://<engine domain>`;
   - every vendor key you have ([WIRING_CHECKLIST.md](../WIRING_CHECKLIST.md)).
5. **Start.**

   ```bash
   docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build --wait
   ```

   Then check `https://<app domain>/api/readyz`, make the first staff admin (below), and look at `GET /admin/providers`.
6. **Backups off the machine.** Copy `deploy/backups` to encrypted storage elsewhere every day (for example `rclone sync` to an R2 bucket from the host's cron), and do the restore drill in [backup-restore.md](backup-restore.md) once before launch.

Upgrades on the VM: `git pull`, then the same `up -d --build --wait` command; the rules under **Upgrade** below still apply.

## First deploy (any host)

```bash
docker compose -f deploy/docker-compose.yml up -d --build --wait    # on a host: your equivalent
uv run python scripts/compose_smoke.py                              # prints COMPOSE HEALTHY
```

The `migrate` service applies every migration and seeds the voice catalog; both are safe to repeat. Then check `GET /readyz` (200 with Postgres and Redis up) and `GET /admin/providers` with a staff token: each vendor shows `configured`, `missing_key` or `unhealthy`.

**Make the first staff admin** (there is no sign-up for staff): sign up as a normal user, then

```sql
UPDATE users SET is_platform_admin = true WHERE email = 'you@example.com';
```

Then sign in again: staff set up an authenticator app at their first sign-in and give a code at every sign-in after (only such a session opens the console). Store the ten recovery codes it shows. A staff member who lost both is reset by another staff member from the account's page in the console (`POST /admin/users/{user_id}/second-factor/reset`, logged); if no other staff member can sign in, clear it in SQL: `UPDATE users SET totp_secret = NULL, totp_enabled_at = NULL, totp_last_step = NULL, recovery_code_hashes = '{}', tokens_valid_after = now() WHERE email = '...'`.

## Upgrade

1. Take a backup first ([backup-restore.md](backup-restore.md)). Migrations only move forward in production.
2. Build and start the new images; `migrate` runs before `api` and `worker` start.
3. Check `GET /readyz`, then `GET /admin/system` (database, Redis, the worker's heartbeat) and `GET /admin/alerts`.

Calls in progress are on the engine: restart `engine` last, when `GET /admin/capacity` shows no calls in flight, or accept that those calls end.

## Roll back

A new image that misbehaves but made no schema change: start the previous image. If the upgrade ran a migration, either keep the new schema (the previous image usually ignores added columns) or restore the backup taken in step 1 into a new database and point `DATABASE_URL` at it. Do not run `alembic downgrade` on production data without a backup and a reason.
