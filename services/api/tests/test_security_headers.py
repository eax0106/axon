"""The dashboard's browser security headers (security test 26 Nov, L2): Caddy in production and
nginx in Compose send them, and the CSP allows the one inline script by its exact hash."""

import base64
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CADDY = (ROOT / "deploy/Caddyfile").read_text()
NGINX = (ROOT / "deploy/nginx.conf").read_text()
NGINX_HEADERS = (ROOT / "deploy/nginx-security-headers.conf").read_text()


def _inline_script_hash() -> str:
    html = (ROOT / "apps/web/index.html").read_text()
    (script,) = re.findall(r"<script>(.*?)</script>", html, re.S)
    return "'sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() + "'"


def _app_site() -> str:
    return CADDY.split("{$AXON_APP_DOMAIN} {", 1)[1].split("\n}\n", 1)[0]


def _csp(text: str) -> dict[str, list[str]]:
    (policy,) = re.findall(r'Content-Security-Policy "([^"]+)"', text)
    parts = (p.split() for p in policy.split(";") if p.strip())
    return {name: values for name, *values in parts}


def test_both_servers_send_the_policy_and_it_allows_only_our_own_scripts() -> None:
    for text in (_app_site(), NGINX_HEADERS):
        csp = _csp(text)
        assert csp["script-src"] == ["'self'", _inline_script_hash()]
        assert csp["frame-ancestors"] == ["'none'"] and csp["object-src"] == ["'none'"]
        assert "'unsafe-inline'" not in csp["script-src"] and "'unsafe-eval'" not in str(csp)
        assert re.search(r'X-Content-Type-Options "nosniff"', text)
        assert re.search(r'Referrer-Policy "no-referrer"', text)
    assert "Strict-Transport-Security" in _app_site() and "defer" in _app_site()
    assert "Strict-Transport-Security" not in NGINX_HEADERS  # plain HTTP in Compose


def test_nginx_sends_them_from_every_location_that_sets_its_own_headers() -> None:
    include = "include /etc/nginx/security-headers.conf;"
    blocks = re.split(r"\n  location ", NGINX)
    assert include in blocks[0]  # the server level, inherited by locations without add_header
    for block in blocks[1:]:
        if "add_header" in block:
            assert include in block, block.splitlines()[0]
    dockerfile = (ROOT / "deploy/web.Dockerfile").read_text()
    assert "COPY deploy/nginx-security-headers.conf /etc/nginx/security-headers.conf" in dockerfile
