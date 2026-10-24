"""Employee lifecycle: draft -> training -> live <-> paused.

  publish   draft -> training (the first publish makes the employee ready to test and teach)
  activate  training | paused -> live   needs a number and a published version
  deactivate live -> paused
Reset and switch-mode put an employee back to draft (see service.py).
"""

from enum import StrEnum

from app.models import EmployeeStatus


class Action(StrEnum):
    PUBLISH = "publish"
    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"


class TransitionError(Exception):
    """The move is not allowed; the message is shown to the user."""


def next_status(
    current: EmployeeStatus, action: Action, *, has_number: bool, has_version: bool
) -> EmployeeStatus:
    """The status after `action`, or TransitionError. Pure: no database."""
    if action is Action.PUBLISH:
        return EmployeeStatus.TRAINING if current is EmployeeStatus.DRAFT else current
    if action is Action.ACTIVATE:
        if current is EmployeeStatus.LIVE:
            raise TransitionError("already live")
        if not has_version:
            raise TransitionError("publish the script before going live")
        if current is EmployeeStatus.DRAFT:
            raise TransitionError("publish the script before going live")
        if not has_number:
            raise TransitionError("attach a phone number before going live")
        return EmployeeStatus.LIVE
    if current is not EmployeeStatus.LIVE:
        raise TransitionError("only a live employee can be paused")
    return EmployeeStatus.PAUSED
