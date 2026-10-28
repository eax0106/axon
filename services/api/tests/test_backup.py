import importlib.util
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from .conftest import alembic, sql

SCRIPT = Path(__file__).parents[3] / "scripts" / "backup.py"
spec = importlib.util.spec_from_file_location("backup_script", SCRIPT)
assert spec and spec.loader
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


@pytest.fixture(autouse=True)
def _pg_tools() -> None:
    if all(shutil.which(tool) for tool in ("pg_dump", "pg_restore", "psql")):
        return
    if os.environ.get("CI"):
        pytest.fail("the PostgreSQL client tools must be installed in CI")
    pytest.skip("pg_dump, pg_restore and psql are not on PATH")


def table_counts(url: str) -> dict[str, int]:
    names = sql(
        url, "SELECT string_agg(tablename, ',') FROM pg_tables WHERE schemaname = 'public'"
    ).split(",")
    return {name: sql(url, f'SELECT count(*) FROM "{name}"') for name in sorted(names)}  # noqa: S608


@pytest.fixture
def source(fresh_database: Any, monkeypatch: pytest.MonkeyPatch) -> str:
    url: str = fresh_database()
    alembic(url, monkeypatch, ("upgrade", "head"))
    account = sql(url, "INSERT INTO accounts (name) VALUES ('Backup Co') RETURNING id::text")
    sql(
        url,
        "INSERT INTO users (account_id, email, password_hash, role) "
        "VALUES (:a, 'b@example.com', 'x', 'owner')",
        {"a": account},
    )
    return url


def test_a_dump_restores_into_a_new_database_with_the_same_rows(
    source: str, fresh_database: Any, tmp_path: Path
) -> None:
    file = backup.dump(source, tmp_path, keep=14)
    assert file.suffix == ".dump" and file.stat().st_size > 0
    assert list(tmp_path.glob("*.partial")) == []
    target: str = fresh_database()
    backup.restore(file, target)
    counts = table_counts(source)
    assert counts["accounts"] == 1 and counts["users"] == 1 and counts["alembic_version"] == 1
    assert table_counts(target) == counts


def test_restoring_into_a_database_that_has_tables_is_refused(
    source: str, migrated_url: str, tmp_path: Path
) -> None:
    file = backup.dump(source, tmp_path, keep=14)
    with pytest.raises(SystemExit, match="already has"):
        backup.restore(file, migrated_url)


def test_dumps_beyond_the_keep_count_are_removed_and_other_files_are_not(
    source: str, tmp_path: Path
) -> None:
    for stamp in ("20200101-000000", "20200102-000000", "20200103-000000"):
        (tmp_path / f"axon-{stamp}.dump").write_bytes(b"old")
    (tmp_path / "notes.txt").write_text("keep me")
    new = backup.dump(source, tmp_path, keep=2)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "axon-20200103-000000.dump",
        new.name,
        "notes.txt",
    ]


def test_a_failed_dump_leaves_no_file_behind(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="pg_dump"):
        backup.dump("postgresql://axon:axon@127.0.0.1:1/none", tmp_path, keep=2)
    assert list(tmp_path.iterdir()) == []
