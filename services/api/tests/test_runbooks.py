import re
from pathlib import Path

ROOT = Path(__file__).parents[3]
RUNBOOKS = ROOT / "docs" / "runbooks"
NEEDED = {"deploy", "backup-restore", "incidents", "capacity", "secrets"}
ROUTE = (
    r"`(?:GET |POST |PUT |DELETE |PATCH )?(/(?:admin|calls|developer|employees|auth)/[\w/{}-]+)`"
)
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")


def pages() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8") for p in RUNBOOKS.glob("*.md")}


def test_there_is_a_runbook_for_each_job_and_the_index_links_each() -> None:
    found = pages()
    assert NEEDED <= found.keys()
    for name in NEEDED:
        assert f"({name}.md)" in found["README"]


def test_every_setting_a_runbook_names_is_in_env_example() -> None:
    named = {v for text in pages().values() for v in re.findall(r"\bAXON_[A-Z0-9_]+\b", text)}
    missing = sorted(v for v in named if v not in ENV_EXAMPLE and v != "AXON_JWT_SECRET")
    assert missing == []
    assert "AXON_JWT_SECRET" in ENV_EXAMPLE
    assert "AXON_MAX_CONCURRENT_CALLS" in named
    assert "FORWARDED_ALLOW_IPS" in ENV_EXAMPLE and "FORWARDED_ALLOW_IPS" in pages()["deploy"]


def test_every_script_and_file_a_runbook_names_exists() -> None:
    named = {
        m
        for text in pages().values()
        for m in re.findall(r"`?((?:scripts|deploy|docs|services)/[\w./-]+\.\w+)", text)
    }
    assert {"scripts/backup.py", "scripts/load_test.py", "scripts/compose_smoke.py"} <= named
    assert sorted(n for n in named if not (ROOT / n).exists()) == []


def test_every_admin_route_a_runbook_names_exists() -> None:
    from .test_route_security import operations

    real = {p for _, p in operations()} | {f"{m} {p}" for m, p in operations()}
    named = {
        re.sub(r"\{[^}]*\}", "{x}", route)
        for text in pages().values()
        for route in re.findall(ROUTE, text)
    }
    normal = {re.sub(r"\{[^}]*\}", "{x}", r) for r in real}
    assert sorted(n for n in named if n not in normal) == []
    assert len(named) > 10
