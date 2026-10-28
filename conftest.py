import os

import pytest


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip `@pytest.mark.requires_keys("SARVAM_API_KEY", ...)` until every named key is set."""
    for marker in item.iter_markers("requires_keys"):
        missing = [key for key in marker.args if not os.environ.get(key)]
        if missing:
            pytest.skip(f"requires_keys: {', '.join(missing)} not set")


@pytest.fixture(autouse=True)
def _no_auth_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests sign in from one address by the hundred; test_auth_rate_limit turns it back on."""
    monkeypatch.setenv("AXON_AUTH_RATE_LIMIT", "off")
