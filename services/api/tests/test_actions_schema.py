from typing import Any

import pytest
from pydantic import ValidationError

from app.actions.schema import MASK, HttpApi, keep_secrets, mask
from app.employees.script import ScriptBundle

from .actions_support import calendar_action, http_action, sheet_write


def bundle(*actions: dict[str, Any]) -> ScriptBundle:
    return ScriptBundle.model_validate({"actions": list(actions)})


def refused(*actions: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as caught:
        bundle(*actions)
    return str(caught.value)


def test_an_employee_has_no_actions_until_the_owner_adds_them() -> None:
    assert ScriptBundle().actions == []


def test_every_kind_is_accepted_with_sensible_defaults() -> None:
    whatsapp = {"kind": "whatsapp", "name": "send_price", "description": "d", "template": "price_1"}
    read = {"kind": "sheet_read", "name": "find", "description": "d", "sheet_id": "sheet-1"}
    got = bundle(http_action(), calendar_action(), sheet_write(), read, whatsapp)
    assert [a.kind for a in got.actions] == [
        "http_api", "calendar_booking", "sheet_write", "sheet_read", "whatsapp"
    ]  # fmt: skip
    assert got.actions[1].days == [0, 1, 2, 3, 4, 5] and got.actions[1].duration_min == 30  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"url": "http://shop.example.in/o"}, "https://"),
        ({"url": "https://user:pw@shop.example.in/o"}, "login"),
        ({"url": "https://shop.example.in:8443/o"}, "standard https port"),
        ({"url": "https://{host}.example.in/o"}, "not in the host"),
        ({"url": "https://shop.example.in/{missing}"}, "not a parameter"),
        ({"headers": {"Host": "evil.example"}}, "set for you"),
        ({"headers": {"X-Note": "a\r\nInjected: 1"}}, "one printable line"),
        ({"auth": {"kind": "bearer"}}, "secret is needed"),
        ({"auth": {"kind": "header", "header": "Authorization", "secret": "s"}}, "set for you"),
        ({"auth": {"kind": "bearer", "secret": "a\nb"}}, "one line"),
        ({"timeout_s": 60}, "less than or equal to 15"),
        ({"name": "Not Valid"}, "lowercase"),
    ],
)
def test_a_bad_http_action_is_refused_with_a_reason(change: dict[str, Any], reason: str) -> None:
    assert reason in refused(http_action(**change))


def test_the_other_kinds_refuse_what_cannot_work() -> None:
    assert "shorter than one appointment" in refused(
        calendar_action(start_hour=10, end_hour=10, duration_min=30)
    )
    assert "distinct numbers" in refused(calendar_action(days=[0, 7]))
    assert "duplicate parameter" in refused(
        sheet_write(columns=[{"name": "a", "description": "x"}, {"name": "a", "description": "y"}])
    )
    assert "not a valid sheet id" in refused(sheet_write(sheet_id="../x"))
    whatsapp = {"kind": "whatsapp", "name": "w", "description": "d", "template": "bad/template"}
    assert "template name" in refused(whatsapp)


def test_tool_names_are_unique_and_never_the_ones_the_call_already_uses() -> None:
    assert "own name" in refused(http_action(), http_action())
    assert "own name" in refused(calendar_action(name="x"), http_action(name="x_book"))
    assert "end_call" in refused(http_action(name="end_call"))
    assert "transfer_to_human" in refused(http_action(name="transfer_to_human"))


def test_at_most_ten_actions() -> None:
    many = [http_action(name=f"a{i}") for i in range(11)]
    assert "at most 10" in refused(*many)


def secret_action(secret: str = "tok-123") -> dict[str, Any]:  # noqa: S107
    return http_action(auth={"kind": "bearer", "secret": secret})


def test_masking_hides_the_secret_and_leaves_everything_else() -> None:
    shown = mask(bundle(secret_action(), calendar_action()).actions)
    assert isinstance(shown[0], HttpApi) and shown[0].auth.secret == MASK
    assert "tok-123" not in str([a.model_dump() for a in shown])


def test_sending_the_mask_back_keeps_the_stored_secret_and_a_new_secret_replaces_it() -> None:
    stored = bundle(secret_action()).actions
    kept = keep_secrets(mask(stored), stored)
    assert isinstance(kept[0], HttpApi) and kept[0].auth.secret == "tok-123"  # noqa: S105
    changed = keep_secrets(bundle(secret_action("new-one")).actions, stored)
    assert isinstance(changed[0], HttpApi) and changed[0].auth.secret == "new-one"  # noqa: S105


def test_a_mask_with_nothing_stored_is_refused_rather_than_saved_as_a_password() -> None:
    with pytest.raises(ValueError, match="send the secret"):
        keep_secrets(bundle(secret_action(MASK)).actions, [])
    renamed = bundle(secret_action(), http_action(name="other")).actions
    with pytest.raises(ValueError, match="send the secret"):
        keep_secrets(bundle(secret_action(MASK)).actions[:1], renamed[1:])
