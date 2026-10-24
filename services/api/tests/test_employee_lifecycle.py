import pytest

from app.employees.lifecycle import Action, TransitionError, next_status
from app.models import EmployeeStatus as S


def move(current: S, action: Action, number: bool = True, version: bool = True) -> S:
    return next_status(current, action, has_number=number, has_version=version)


def test_first_publish_moves_draft_to_training_and_later_publishes_keep_the_status() -> None:
    assert move(S.DRAFT, Action.PUBLISH) is S.TRAINING
    for status in (S.TRAINING, S.LIVE, S.PAUSED):
        assert move(status, Action.PUBLISH) is status


@pytest.mark.parametrize("status", [S.TRAINING, S.PAUSED])
def test_activate_goes_live_from_training_or_paused(status: S) -> None:
    assert move(status, Action.ACTIVATE) is S.LIVE


def test_activate_needs_a_number_and_a_published_version() -> None:
    with pytest.raises(TransitionError, match="phone number"):
        move(S.TRAINING, Action.ACTIVATE, number=False)
    with pytest.raises(TransitionError, match="publish"):
        move(S.TRAINING, Action.ACTIVATE, version=False)
    with pytest.raises(TransitionError, match="publish"):
        move(S.DRAFT, Action.ACTIVATE)
    with pytest.raises(TransitionError, match="already live"):
        move(S.LIVE, Action.ACTIVATE)


def test_deactivate_pauses_only_a_live_employee() -> None:
    assert move(S.LIVE, Action.DEACTIVATE) is S.PAUSED
    for status in (S.DRAFT, S.TRAINING, S.PAUSED):
        with pytest.raises(TransitionError):
            move(status, Action.DEACTIVATE)
