import os

import pytest


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip `@pytest.mark.requires_keys("SARVAM_API_KEY", ...)` until every named key is set."""
    for marker in item.iter_markers("requires_keys"):
        missing = [key for key in marker.args if not os.environ.get(key)]
        if missing:
            pytest.skip(f"requires_keys: {', '.join(missing)} not set")
