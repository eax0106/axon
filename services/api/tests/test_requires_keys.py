from pathlib import Path

import pytest

ROOT_CONFTEST = Path(__file__).parents[3] / "conftest.py"


def test_requires_keys_marker_skips_until_keys_exist(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(ROOT_CONFTEST.read_text(encoding="utf-8"))
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.requires_keys("AXON_TEST_KEY_THAT_IS_NEVER_SET")
        def test_needs_key():
            raise AssertionError("must not run")

        def test_plain():
            pass
        """
    )
    pytester.runpytest().assert_outcomes(passed=1, skipped=1)
