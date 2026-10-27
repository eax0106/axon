import asyncio
from typing import Any

import httpx
import pytest

from app.actions import http_tool, net
from app.actions.schema import HttpApi

from .actions_support import http_action

PUBLIC = "93.184.216.34"


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.1.1", "169.254.169.254", "100.64.0.1",
        "0.0.0.0",  # noqa: S104 - the address to refuse, not one we bind
        "::1", "fe80::1", "fd00::1", "::ffff:127.0.0.1", "224.0.0.1",
    ],
)  # fmt: skip
def test_an_address_inside_a_network_is_never_allowed(address: str) -> None:
    with pytest.raises(net.BlockedError):
        asyncio.run(net.resolve(address, 443))


def test_a_public_address_is_allowed_as_it_is() -> None:
    assert asyncio.run(net.resolve(PUBLIC, 443)) == PUBLIC


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("ftp://shop.example.in/x", "https://"),
        ("http://shop.example.in/x", "https://"),
        ("https://u:p@shop.example.in/x", "login"),
        ("https://shop.example.in:99999/x", "valid web address"),
        ("https://shop.example.in:8443/x", "standard https port"),
        ("https:///x", "no host"),
        ("https://shop.example.in/x#frag", "# part"),
    ],
)
def test_the_address_rules(url: str, reason: str) -> None:
    assert reason in (net.url_problem(url) or "")
    assert net.url_problem("https://shop.example.in/x?y=1") is None


def patch_lookup(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> None:
    async def lookup(host: str, port: int) -> list[str]:
        return list(addresses)

    monkeypatch.setattr(net, "_lookup", lookup)


def run(args: dict[str, Any], transport: httpx.MockTransport | None = None) -> dict[str, Any]:
    action = HttpApi.model_validate(http_action())
    return asyncio.run(http_tool.call(action, args, transport))


def test_the_request_goes_to_the_address_that_was_checked_under_the_name_the_owner_wrote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_lookup(monkeypatch, PUBLIC)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": 1})

    result = run({"order_id": "42"}, httpx.MockTransport(handler))
    assert result["ok"] is True
    request = seen[0]
    assert request.url.host == PUBLIC and request.url.path == "/orders/42"
    assert request.headers["host"] == "shop.example.in"
    assert (
        request.extensions["sni_hostname"] == "shop.example.in"
    )  # the certificate is for the name


def test_a_name_with_one_inside_address_among_its_answers_is_not_followed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_lookup(monkeypatch, PUBLIC, "10.0.0.7")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    result = run({"order_id": "42"}, httpx.MockTransport(handler))
    assert result == {"ok": False, "error": "that address is not allowed"} and seen == []


def test_a_name_that_does_not_resolve_is_a_plain_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_lookup(monkeypatch)
    assert run({"order_id": "1"})["ok"] is False
