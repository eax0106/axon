"""An employee's own result webhook: after a call that reached a person, the result goes to the
owner's address (a CRM, n8n, Zapier). It lives in the script bundle, so it shares the publish
gate, the last three versions and restore with the script and the actions.

The optional secret signs each send (see delivery.sign). Like an action's secret it is stored but
never sent back: reads show MASK, and sending MASK back keeps the stored one.
"""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from app.actions import net
from app.actions.schema import MASK

Trigger = Literal["all_connected", "skip_voicemail", "voicemail_only"]


class ResultWebhook(BaseModel):
    url: str = Field(max_length=500)
    trigger: Trigger = "all_connected"
    secret: str = Field(default="", max_length=500)

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        problem = net.url_problem(value)
        if problem:
            raise ValueError(problem)
        return value

    @field_validator("secret")
    @classmethod
    def _one_line(cls, value: str) -> str:
        if "\r" in value or "\n" in value:
            raise ValueError("a secret is one line")
        return value

    def wants(self, *, voicemail: bool) -> bool:
        """Whether a call that reached someone (or a voicemail greeting) is sent."""
        if self.trigger == "voicemail_only":
            return voicemail
        return not voicemail or self.trigger == "all_connected"


def mask(hook: ResultWebhook | None) -> ResultWebhook | None:
    return hook.model_copy(update={"secret": MASK}) if hook and hook.secret else hook


def keep_secret(
    incoming: ResultWebhook | None, stored: ResultWebhook | None
) -> ResultWebhook | None:
    """Put back the stored secret where the caller sent MASK. A mask with nothing stored is
    refused (it would save the word as a secret), and so is one for another host: the secret was
    given for the old address."""
    if incoming is None or incoming.secret != MASK:
        return incoming
    if stored is None or not stored.secret:
        raise ValueError("send the secret again")
    if urlsplit(incoming.url).netloc.lower() != urlsplit(stored.url).netloc.lower():
        raise ValueError("send the secret again: the address now points to another host")
    return incoming.model_copy(update={"secret": stored.secret})
