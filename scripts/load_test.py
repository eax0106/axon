"""Load test the API: many simulated users sign up, sign in and read their dashboard at once.

    uv run python scripts/load_test.py --base-url http://localhost:8000 --users 50 --rounds 20

Prints p50, p95 and p99 latency per route and the error count; exits 1 on any error or when the
p95 of a read route is above --max-p95-ms. The target server needs AXON_AUTH_RATE_LIMIT=off, or
its sign-up limit refuses the test. This measures the API and database only. How many calls the
voice engine carries is measured with real calls at wiring (docs/runbooks/capacity.md).
"""

import argparse
import asyncio
import math
import secrets
import sys
import time
from dataclasses import dataclass, field

import httpx

READS = (
    "/accounts/me",
    "/employees",
    "/calls",
    "/leads",
    "/campaigns",
    "/stats/overview",
    "/wallet",
    "/notifications",
    "/voices",
    "/billing/rates",
)
PASSWORD = "load-test-password"  # noqa: S105 - a throwaway user on the server under test


@dataclass
class Report:
    latencies: dict[str, list[float]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    refused_by_rate_limit: bool = False
    max_p95_ms: float = 0.0

    def add(self, route: str, seconds: float) -> None:
        self.latencies.setdefault(route, []).append(seconds * 1000)

    def percentile(self, route: str, q: float) -> float:
        values = sorted(self.latencies[route])
        return values[max(0, math.ceil(q * len(values)) - 1)]

    def slow(self) -> list[str]:
        if not self.max_p95_ms:
            return []
        return [
            r for r in READS if r in self.latencies and self.percentile(r, 0.95) > self.max_p95_ms
        ]

    @property
    def ok(self) -> bool:
        return not self.errors and not self.refused_by_rate_limit and not self.slow()

    def render(self) -> str:
        lines = [f"{'route':<18}{'count':>7}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}"]
        for route, values in self.latencies.items():
            p = (self.percentile(route, q) for q in (0.5, 0.95, 0.99))
            lines.append(f"{route:<18}{len(values):>7}" + "".join(f"{x:>9.1f}" for x in p))
        lines.append(f"errors: {len(self.errors)}")
        lines += [f"  {e}" for e in self.errors[:10]]
        if self.refused_by_rate_limit:
            lines.append(
                "the server's rate limit refused the test: set AXON_AUTH_RATE_LIMIT=off there"
            )
        lines += [f"p95 above {self.max_p95_ms:g} ms: {route}" for route in self.slow()]
        lines.append("LOAD TEST PASSED" if self.ok else "LOAD TEST FAILED")
        return "\n".join(lines)


async def timed(
    report: Report, client: httpx.AsyncClient, method: str, route: str, **kwargs: object
) -> httpx.Response | None:
    started = time.perf_counter()
    try:
        response = await client.request(method, route, **kwargs)  # type: ignore[arg-type]
    except httpx.HTTPError as exc:
        report.errors.append(f"{method} {route}: {type(exc).__name__}")
        return None
    report.add(route, time.perf_counter() - started)
    if response.status_code == 429:
        report.refused_by_rate_limit = True
    elif response.status_code >= 400:
        report.errors.append(f"{method} {route}: {response.status_code}")
    return response if response.is_success else None


async def one_user(report: Report, client: httpx.AsyncClient, email: str, rounds: int) -> None:
    body = {"email": email, "password": PASSWORD}
    if (
        await timed(report, client, "POST", "/auth/signup", json={**body, "account_name": "Load"})
        is None
    ):
        return
    signed_in = await timed(report, client, "POST", "/auth/login", json=body)
    if signed_in is None:
        return
    headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}
    for _ in range(rounds):
        for route in READS:
            await timed(report, client, "GET", route, headers=headers)


async def run(
    base_url: str,
    users: int,
    rounds: int,
    max_p95_ms: float = 0.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Report:
    report = Report(max_p95_ms=max_p95_ms)
    run_id = secrets.token_hex(4)
    # Idle connections are dropped before the server's own 5 s keep-alive closes them.
    limits = httpx.Limits(max_connections=users, keepalive_expiry=2)
    async with httpx.AsyncClient(
        base_url=base_url, timeout=30, limits=limits, transport=transport
    ) as client:
        await asyncio.gather(
            *(
                one_user(report, client, f"load-{run_id}-{n}@example.com", rounds)
                for n in range(users)
            )
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument(
        "--max-p95-ms", type=float, default=0.0, help="fail above this; 0 = no limit"
    )
    args = parser.parse_args()
    report = asyncio.run(run(args.base_url, args.users, args.rounds, args.max_p95_ms))
    print(report.render())
    sys.exit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
