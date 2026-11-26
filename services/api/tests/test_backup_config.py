"""Production backups are encrypted before they touch the disk (security test 26 Nov, L3). The
script itself was run against a real Postgres with a throwaway key when this was written; this
keeps the Compose file from drifting back to plain dumps."""

from pathlib import Path

PROD = (Path(__file__).resolve().parents[3] / "deploy/docker-compose.prod.yml").read_text()


def _section(start: str, end: str) -> str:
    return PROD.split(start, 1)[1].split(end, 1)[0]


def test_every_dump_goes_through_gpg_to_the_owners_key_and_is_kept_only_when_whole() -> None:
    script = _section("  backup_script:\n    content: |\n", "\nvolumes:")
    assert script.lstrip().startswith("set -uo pipefail\n")  # a failed pg_dump fails the pipe
    assert "umask 077" in script
    assert "pg_dump -Fc | gpg --batch" in script and "--recipient-file /backup-key.asc" in script
    assert script.count("pg_dump") == 1  # the one dump is the piped one: none is written plain
    assert '--output "$$name.part"' in script and 'mv "$$name.part" "$$name"' in script
    assert 'name="/backups/axon-$$(date -u +%Y%m%dT%H%M%SZ).dump.gpg"' in script


def test_the_backup_service_needs_the_public_key_and_runs_the_script_under_bash() -> None:
    backup = _section("\n  backup:\n", "\nconfigs:")
    assert 'entrypoint: ["bash", "/backup.sh"]' in backup  # pipefail is bash, not sh
    assert "- ./backup-public-key.asc:/backup-key.asc:ro" in backup
