import asyncio

import pytest

from app.providers.base import ProviderKind
from app.providers.registry import require
from app.providers.telephony.vobiz import VobizTelephony


def test_vobiz_is_the_registered_telephony_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_TEST")
    monkeypatch.setenv("VOBIZ_AUTH_TOKEN", "token")
    monkeypatch.delenv("AXON_TELEPHONY_PROVIDER", raising=False)
    assert isinstance(require(ProviderKind.TELEPHONY), VobizTelephony)


@pytest.mark.requires_keys("VOBIZ_AUTH_ID", "VOBIZ_AUTH_TOKEN")
def test_vobiz_accepts_our_credentials() -> None:
    asyncio.run(VobizTelephony().health())
