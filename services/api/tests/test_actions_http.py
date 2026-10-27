"""The custom HTTP tool against a real web server on this machine."""

import asyncio
import json
from typing import Any

from app.actions import http_tool
from app.actions.schema import HttpApi

from .actions_support import Shop, http_action


def call(
    shop: str, args: dict[str, Any], path: str = "/orders/{order_id}", **changes: Any
) -> dict[str, Any]:
    action = HttpApi.model_validate(http_action(url=shop + path, **changes))
    return asyncio.run(http_tool.call(action, args))


def test_a_get_fills_the_path_and_returns_the_answer(shop: str) -> None:
    result = call(shop, {"order_id": "42"})
    assert result["ok"] is True and result["status"] == 200
    assert json.loads(result["result"])["path"] == "/orders/42"
    assert Shop.seen[0]["headers"]["Host"].startswith("127.0.0.1")


def test_values_cannot_leave_the_path_they_were_put_in(shop: str) -> None:
    call(shop, {"order_id": "../../admin?x=1#"})
    assert Shop.seen[0]["path"] == "/orders/..%2F..%2Fadmin%3Fx%3D1%23"


def test_unnamed_values_go_in_the_query_for_a_get_and_a_json_body_for_a_post(shop: str) -> None:
    params = [
        {"name": "order_id", "description": "id"},
        {"name": "note", "description": "a note", "required": False},
        {"name": "qty", "description": "how many", "type": "number", "required": False},
    ]
    call(shop, {"order_id": "7", "note": "a&b=c", "qty": "3"}, params=params)
    assert Shop.seen[0]["path"] == "/orders/7?note=a%26b%3Dc&qty=3"
    call(shop, {"order_id": "7", "note": "hi", "qty": 3}, params=params, method="POST")
    assert Shop.seen[1]["method"] == "POST" and json.loads(Shop.seen[1]["body"]) == {
        "note": "hi", "qty": 3
    }  # fmt: skip
    assert Shop.seen[1]["headers"]["Content-Type"] == "application/json"


def test_the_secret_goes_out_in_the_chosen_header_and_other_headers_as_written(shop: str) -> None:
    call(
        shop, {"order_id": "1"}, auth={"kind": "bearer", "secret": "tok-9"}, headers={"X-Shop": "a"}
    )
    assert Shop.seen[0]["headers"]["Authorization"] == "Bearer tok-9"
    assert Shop.seen[0]["headers"]["X-Shop"] == "a"
    call(shop, {"order_id": "1"}, auth={"kind": "header", "header": "X-Api-Key", "secret": "k"})
    assert Shop.seen[1]["headers"]["X-Api-Key"] == "k"


def test_missing_and_badly_typed_values_are_named_and_nothing_is_sent(shop: str) -> None:
    assert call(shop, {}) == {"ok": False, "error": "order_id is needed"}
    number = [{"name": "order_id", "description": "id", "type": "number"}]
    assert call(shop, {"order_id": "abc"}, params=number)["error"] == "order_id must be a number"
    assert Shop.seen == []


def test_a_redirect_is_not_followed(shop: str) -> None:
    result = call(shop, {"order_id": "x"}, "/redirect/{order_id}")
    assert result["ok"] is False and result["status"] == 302
    assert len(Shop.seen) == 1  # the address in the Location header was never asked


def test_an_error_status_is_a_plain_failure_with_the_services_words(shop: str) -> None:
    result = call(shop, {"order_id": "x"}, "/boom/{order_id}")
    assert result["ok"] is False and result["status"] == 500
    assert "refused or failed" in result["error"] and "/boom/x" in result["detail"]


def test_a_huge_answer_is_cut_and_a_slow_one_gives_up(shop: str) -> None:
    big = call(shop, {"order_id": "x"}, "/big/{order_id}")
    assert big["ok"] is True and big["cut"] is True and len(big["result"]) == 2000
    slow = call(shop, {"order_id": "x"}, "/slow/{order_id}", timeout_s=1)
    assert slow == {"ok": False, "error": "the service did not answer in time"}


def test_a_service_that_is_down_is_a_plain_failure() -> None:
    action = HttpApi.model_validate(http_action(url="https://shop.example.in/o/{order_id}"))
    # No server and no DNS answer in the test: the failure is reported, not raised.
    result = asyncio.run(http_tool.call(action, {"order_id": "1"}))
    assert result["ok"] is False and isinstance(result["error"], str)
