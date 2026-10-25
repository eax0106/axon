"""Real-use contract tests for what B5 asks of Meta, Google and Vobiz. Skipped until the keys
(and, for the Graph and Sheets reads, a real lead id / sheet) are set (`requires_keys`).

META_TEST_LEADGEN_ID + META_TEST_PAGE_TOKEN: a lead id and the page token that can read it.
GOOGLE_TEST_REFRESH_TOKEN + GOOGLE_TEST_SHEET_ID: a refresh token for a sheet owner and the sheet.
VOBIZ_TEST_CALL_UUID: the uuid of a finished call on the account.
"""

import asyncio
import os

import pytest

from app.providers.google.sheets import GoogleSheets
from app.providers.leads.meta_lead_ads import MetaLeadAds
from app.providers.telephony.vobiz import VobizTelephony


@pytest.mark.requires_keys("META_APP_ID", "META_APP_SECRET", "META_VERIFY_TOKEN")
def test_meta_accepts_our_app_id_and_secret() -> None:
    asyncio.run(MetaLeadAds().health())


@pytest.mark.requires_keys(
    "META_APP_ID", "META_APP_SECRET", "META_TEST_LEADGEN_ID", "META_TEST_PAGE_TOKEN"
)
def test_meta_returns_a_leads_answers() -> None:
    fields = asyncio.run(
        MetaLeadAds().fetch_lead(
            os.environ["META_TEST_LEADGEN_ID"], os.environ["META_TEST_PAGE_TOKEN"]
        )
    )
    assert fields


@pytest.mark.requires_keys("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET")
def test_google_accepts_our_oauth_client() -> None:
    asyncio.run(GoogleSheets().health())


@pytest.mark.requires_keys(
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_TEST_REFRESH_TOKEN",
    "GOOGLE_TEST_SHEET_ID",
)
def test_google_returns_the_rows_of_a_sheet() -> None:
    rows = asyncio.run(
        GoogleSheets().read_rows(
            os.environ["GOOGLE_TEST_REFRESH_TOKEN"], os.environ["GOOGLE_TEST_SHEET_ID"], "A:Z"
        )
    )
    assert rows and rows[0]


@pytest.mark.requires_keys("VOBIZ_AUTH_ID", "VOBIZ_AUTH_TOKEN", "VOBIZ_TEST_CALL_UUID")
def test_vobiz_returns_the_record_of_a_finished_call() -> None:
    detail = asyncio.run(VobizTelephony().call_detail(os.environ["VOBIZ_TEST_CALL_UUID"]))
    assert detail is not None and detail.hangup_cause
