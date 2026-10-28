# Backup and restore

**What to back up.** Postgres: everything that matters (accounts, ledger, calls, leads, scripts, secrets). Redis holds only queues and live events: nothing to back up, and a lost Redis only drops waiting work (waiting dials are rebuilt from their database rows by the worker). Recordings live in object storage (Cloudflare R2): turn on its versioning or replication there.

**A dump holds every customer secret** (webhook signing secrets, lead-intake secrets, Google and Meta tokens, tool keys), unencrypted, because the database stores them that way (see `docs/phases/b14-security-review.md`, F5). Keep dumps in encrypted storage with the access of the person who can already read the database. `backups/` and `*.dump` are in `.gitignore`.

## Take a backup

Needs the PostgreSQL 16+ client tools (`pg_dump`, `pg_restore`, `psql`) on PATH.

```bash
uv run python scripts/backup.py dump --dir backups --keep 14
```

It reads `DATABASE_URL` (or pass `--url`), writes `backups/axon-YYYYmmdd-HHMMSS.dump` (a custom-format dump, written under a temporary name and renamed when complete), and deletes older dumps beyond `--keep`. Run it from the host's scheduler (cron, a systemd timer, the host's job runner) at least daily; the dump of a small database takes seconds. Copy the file off the machine afterwards.

With the Compose stack and no client tools on the host, the same dump from inside the container:

```bash
docker compose -f deploy/docker-compose.yml exec -T postgres pg_dump -U axon --format=custom --no-owner --no-privileges axon > backups/axon-manual.dump
```

**Targets.** Recovery point: up to a day of data with a daily dump (run it hourly if that is too much; managed Postgres with point-in-time recovery does better and is the better choice in production). Recovery time: minutes for the restore, plus the time to point the services at it.

## Restore

Into a new, empty database on a server that has the `vector` extension available (the `pgvector/pgvector:pg16` image does):

```bash
createdb -h <host> -U <admin> axon_restored
uv run python scripts/backup.py restore backups/axon-20261028-020000.dump --url postgresql+asyncpg://axon:<password>@<host>:5432/axon_restored
uv run alembic -c services/api/alembic.ini upgrade head     # with DATABASE_URL pointing at the restored database
```

The script refuses a database that already has tables, so it can never overwrite live data. To replace production, restore into a new database, check it ([incidents.md](incidents.md): `GET /admin/system`), stop `api`, `engine` and `worker`, switch `DATABASE_URL`, start them.

## Restore drill

Do this once before launch and after any change to how backups are taken: restore the latest dump into a scratch database, run `alembic upgrade head` on it, start an `api` against it and check `GET /readyz`, sign in as a known user, and compare `SELECT count(*)` of `accounts`, `calls` and `wallet_ledger` with production. `services/api/tests/test_backup.py` does the dump, restore and per-table row comparison on every CI run; the drill proves your host, your credentials and your storage.
