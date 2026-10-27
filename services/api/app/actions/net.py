"""Where the custom HTTP tool may connect. The URL is typed in by the owner, but the values in it
come from a caller on the phone, and a request goes out from our servers: it must never reach our
database, our other services or a cloud metadata address.

The rules: https on the standard port, no credentials in the URL, a host that is not an address
inside a network (checked on every address the name resolves to), and the connection is made to
the address that was checked, so a name that changes its answer afterwards is not followed.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

# Tests only: lets the tool reach a server on this machine over plain http. Never set in the app.
ALLOW_LOCAL = False


class BlockedError(Exception):
    """The address is not one the tool may connect to."""


def url_problem(url: str) -> str | None:
    """Why `url` cannot be used, or None. Placeholders like {name} may appear after the host."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "not a valid web address"
    if parts.scheme != "https" and not (ALLOW_LOCAL and parts.scheme == "http"):
        return "the address must start with https://"
    if not parts.hostname:
        return "the address has no host"
    if parts.username or parts.password:
        return "do not put a login in the address: use the secret field"
    if "{" in parts.netloc or "}" in parts.netloc:
        return "values can go in the path or the query, not in the host"
    if port not in (None, 443) and not ALLOW_LOCAL:
        return "only the standard https port is allowed"
    if parts.fragment:
        return "leave out the # part"
    return None


def _safe(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def _lookup(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def resolve(host: str, port: int) -> str:
    """The address to connect to for `host`: the first one, once every address is checked."""
    try:
        addresses = await _lookup(host, port)
    except OSError:
        addresses = []
    if not addresses:
        raise BlockedError("the name does not resolve")
    if not ALLOW_LOCAL and not all(_safe(a) for a in addresses):
        raise BlockedError("that address is not allowed")
    return addresses[0]
