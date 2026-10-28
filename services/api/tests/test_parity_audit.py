import re
from pathlib import Path

from .test_route_security import operations

ROOT = Path(__file__).parents[3]
PARITY = (ROOT / "docs/PARITY.md").read_text(encoding="utf-8")
AUDIT = (ROOT / "docs/phases/b14-parity-audit.md").read_text(encoding="utf-8")
OUTSIDE = "## Outside the backend"


def backend_rows() -> list[str]:
    inside = PARITY.split(OUTSIDE)[0]
    return [line for line in inside.splitlines() if line.startswith("- [")]


def audit_rows() -> list[list[str]]:
    table = AUDIT.split("## Map check")[0]
    rows = [line.strip("|").split("|") for line in table.splitlines() if line.startswith("| ")]
    return [[cell.strip() for cell in row] for row in rows[1:]]  # the first is the header


def test_the_outside_section_exists_and_holds_only_what_the_backend_cannot_do() -> None:
    assert OUTSIDE in PARITY
    assert len(backend_rows()) > 60


def test_every_backend_row_is_ticked() -> None:
    assert [row[:80] for row in backend_rows() if not row.startswith("- [x]")] == []


def test_every_backend_row_is_mapped_in_the_audit_and_every_mapping_is_to_a_row() -> None:
    texts = [row[len("- [x] ") :] for row in backend_rows()]
    keys = [row[0] for row in audit_rows()]
    unmapped = [t[:80] for t in texts if not any(t.startswith(k) for k in keys)]
    assert unmapped == []
    assert len(keys) == len(texts)


def test_every_route_the_audit_names_exists() -> None:
    real = {f"{m} {p}" for m, p in operations()}
    named = re.findall(r"`((?:GET|POST|PUT|PATCH|DELETE) /[^`]*)`", AUDIT)
    assert len(named) > 150
    assert sorted(set(named) - real) == []


def test_every_row_names_a_route_or_a_test_and_every_test_file_exists() -> None:
    for key, routes, tests in audit_rows():
        files = re.findall(r"`(services/[^`]+\.py)`", tests)
        assert files, f"no test named for: {key}"
        assert routes or files
        for name in files:
            assert (ROOT / name).is_file(), f"{name} (row: {key})"
