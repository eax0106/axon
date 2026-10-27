"""The custom HTTP tool: one request to the owner's web service, with what the AI supplied."""

import asyncio
import json
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from app.actions import net
from app.actions.schema import HttpApi, Param

MAX_BYTES = 65536  # of an answer that is read; the AI is given far less
MAX_REPLY_CHARS = 2000


def coerce(params: list[Param], args: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """The values for the declared parameters, typed, or what is wrong with them."""
    values: dict[str, Any] = {}
    for param in params:
        value = args.get(param.name)
        if value is None or value == "":
            if param.required:
                return {}, f"{param.name} is needed"
            continue
        try:
            if param.type == "number":
                number = float(value)
                values[param.name] = int(number) if number.is_integer() else number
            elif param.type == "boolean":
                if str(value).lower() not in ("true", "false"):
                    raise ValueError
                values[param.name] = str(value).lower() == "true"
            else:
                values[param.name] = str(value)[:500]
        except (TypeError, ValueError):
            return {}, f"{param.name} must be a {param.type}"
    return values, None


def _text(value: Any) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def build(action: HttpApi, values: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """The final URL and JSON body. Values placed in the path are encoded so they cannot add a
    slash, a query or a host; the ones the URL does not name go in the query or the body."""
    url = action.url
    for name in list(values):
        marker = f"{{{name}}}"
        if marker in url:
            url = url.replace(marker, quote(_text(values.pop(name)), safe=""))
    if action.method in ("POST", "PUT", "PATCH"):
        return url, values
    if values:
        parts = urlsplit(url)
        query = "&".join(
            f"{quote(k, safe='')}={quote(_text(v), safe='')}" for k, v in values.items()
        )
        url = urlunsplit(parts._replace(query=f"{parts.query}&{query}" if parts.query else query))
    return url, None


async def _read(response: httpx.Response) -> tuple[str, bool]:
    body = b""
    async for chunk in response.aiter_bytes():
        body += chunk
        if len(body) > MAX_BYTES:
            return body[:MAX_BYTES].decode("utf-8", "replace"), True
    return body.decode("utf-8", "replace"), False


def _reply(text: str) -> str:
    try:
        text = json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":"))
    except ValueError:
        text = " ".join(text.split())
    return text[:MAX_REPLY_CHARS]


async def call(
    action: HttpApi, args: dict[str, Any], transport: httpx.AsyncBaseTransport | None = None
) -> dict[str, Any]:
    """Make the request. Always an answer the AI can use: `ok`, and either `result` or `error`."""
    values, problem = coerce(action.params, args)
    if problem:
        return {"ok": False, "error": problem}
    url, body = build(action, values)
    if net.url_problem(url):  # a value cannot have changed the host, but the rule is the rule
        return {"ok": False, "error": "that address is not allowed"}
    parts = urlsplit(url)
    host, port = parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80)
    headers = dict(action.headers)
    if action.auth.kind == "bearer":
        headers["Authorization"] = f"Bearer {action.auth.secret}"
    elif action.auth.kind == "header":
        headers[action.auth.header] = action.auth.secret
    try:
        async with asyncio.timeout(action.timeout_s):
            address = await net.resolve(host, port)
            shown = f"[{address}]" if ":" in address else address
            pinned = urlunsplit(parts._replace(netloc=f"{shown}:{port}"))
            headers["Host"] = parts.netloc  # the name, so the service sees what it expects
            async with (
                httpx.AsyncClient(timeout=action.timeout_s, transport=transport) as client,
                client.stream(
                    action.method,
                    pinned,
                    headers=headers,
                    json=body if body else None,
                    extensions={"sni_hostname": host},  # the certificate is checked for the name
                ) as response,
            ):
                text, cut = await _read(response)
    except net.BlockedError as exc:
        return {"ok": False, "error": str(exc)}
    except TimeoutError:
        return {"ok": False, "error": "the service did not answer in time"}
    except httpx.HTTPError:
        return {"ok": False, "error": "could not reach the service"}
    status = response.status_code
    if 300 <= status < 400:
        return {
            "ok": False,
            "status": status,
            "error": "the service moved: redirects are not followed",
        }
    if status >= 400:
        return {
            "ok": False,
            "status": status,
            "error": "the service refused or failed",
            "detail": _reply(text)[:300],
        }
    return {"ok": True, "status": status, "result": _reply(text), **({"cut": True} if cut else {})}
