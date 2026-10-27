"""Real-use contract tests for what B7 asks of Razorpay, Vobiz and Resend. Skipped until the keys
are set (`requires_keys`); they only read, except the Razorpay test-mode order, which is free.

Use Razorpay *test mode* keys (rzp_test_...). RESEND_API_KEY needs full access for the domain list.
"""

import asyncio

import pytest

from app.providers.email.resend import ResendEmail
from app.providers.kyc.vobiz import VobizKyc
from app.providers.payments.razorpay import RazorpayPayments
from app.providers.telephony.vobiz import VobizTelephony

RAZORPAY = ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET")
VOBIZ = ("VOBIZ_AUTH_ID", "VOBIZ_AUTH_TOKEN")


@pytest.mark.requires_keys(*RAZORPAY)
def test_razorpay_accepts_our_keys() -> None:
    asyncio.run(RazorpayPayments().health())


@pytest.mark.requires_keys(*RAZORPAY)
def test_razorpay_opens_an_order_in_paise() -> None:
    order = asyncio.run(RazorpayPayments().create_order(10000, "axon_contract_test"))
    assert order.id.startswith("order_")


@pytest.mark.requires_keys(*VOBIZ)
def test_vobiz_lists_numbers_on_sale() -> None:
    numbers = asyncio.run(VobizTelephony().search_numbers("", 1, 5))
    assert numbers and all(n.e164.startswith("+") for n in numbers)


@pytest.mark.requires_keys(*VOBIZ)
def test_vobiz_kyc_endpoint_answers() -> None:
    asyncio.run(VobizKyc().health())  # the KYC paths are the ones WIRING_CHECKLIST #21 confirms


@pytest.mark.requires_keys("RESEND_API_KEY", "EMAIL_FROM")
def test_resend_accepts_our_key() -> None:
    asyncio.run(ResendEmail().health())
