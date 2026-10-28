"""Back up the Postgres database to a dump file, and restore a dump into an empty database.

    uv run python scripts/backup.py dump [--dir backups] [--keep 14] [--url URL]
    uv run python scripts/backup.py restore FILE --url URL

The URL defaults to DATABASE_URL. Needs pg_dump, pg_restore and psql (the PostgreSQL client
tools, version 16 or newer) on PATH. Redis holds only queues and live events, nothing to back up;
recordings live in object storage, which keeps its own copies.
"""

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

PREFIX, SUFFIX = "axon-", ".dump"


def libpq_env(url: str) -> dict[str, str]:
    """The connection as PG* variables, so a password never shows in the process list."""
    parts = urlparse(url.replace("+asyncpg", ""))
    pairs = {
        "PGHOST": parts.hostname,
        "PGPORT": str(parts.port) if parts.port else None,
        "PGUSER": unquote(parts.username) if parts.username else None,
        "PGPASSWORD": unquote(parts.password) if parts.password else None,
        "PGDATABASE": parts.path.lstrip("/") or None,
    }
    return {**os.environ, **{k: v for k, v in pairs.items() if v}}


def dump(url: str, directory: Path, keep: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = directory / f"{PREFIX}{stamp}{SUFFIX}"
    partial = target.with_suffix(".partial")
    command = ["pg_dump", "--format=custom", "--no-owner", "--no-privileges", f"--file={partial}"]
    try:
        subprocess.run(command, env=libpq_env(url), check=True)
    except BaseException:
        partial.unlink(missing_ok=True)  # a half-written dump must never look like a backup
        raise
    partial.chmod(0o600)  # a dump holds every customer secret: owner only
    partial.replace(target)
    for old in sorted(directory.glob(f"{PREFIX}*{SUFFIX}"))[:-keep]:
        old.unlink()
    return target


def restore(file: Path, url: str) -> None:
    env = libpq_env(url)
    tables = subprocess.run(
        ["psql", "--no-psqlrc", "-tAc", "SELECT count(*) FROM pg_tables WHERE schemaname='public'"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if tables != "0":
        sys.exit(f"refusing to restore: the target database already has {tables} tables")
    command = ["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error", "--dbname"]
    subprocess.run([*command, env["PGDATABASE"], str(file)], env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("dump", "restore"):
        step = sub.add_parser(name)
        step.add_argument("--url", default=os.environ.get("DATABASE_URL", ""))
        if name == "dump":
            step.add_argument("--dir", type=Path, default=Path("backups"))
            step.add_argument("--keep", type=int, default=14)
        else:
            step.add_argument("file", type=Path)
    args = parser.parse_args()
    if not args.url:
        sys.exit("no database: pass --url or set DATABASE_URL")
    if args.action == "dump":
        print(dump(args.url, args.dir, max(1, args.keep)))
    else:
        restore(args.file, args.url)
        print("restored; now run: uv run alembic -c services/api/alembic.ini upgrade head")


if __name__ == "__main__":
    main()
