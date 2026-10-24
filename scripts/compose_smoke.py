"""Start the Docker Compose stack, migrated, and prove it works. Prints COMPOSE HEALTHY on success.

Usage: uv run python scripts/compose_smoke.py [--down]
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

COMPOSE = ["docker", "compose", "-f", str(Path(__file__).parents[1] / "deploy/docker-compose.yml")]
API = f"http://localhost:{os.environ.get('AXON_API_PORT', '8000')}"
ENGINE = f"http://localhost:{os.environ.get('AXON_ENGINE_PORT', '8001')}"
MAX_IMAGE_BYTES = 1_000_000_000


def get_json(path: str, base: str = API) -> Any:
    with urllib.request.urlopen(base + path, timeout=5) as response:
        return json.load(response)


def http_error(url: str, method: str = "GET") -> urllib.error.HTTPError:
    try:
        urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=5)
    except urllib.error.HTTPError as exc:
        return exc
    raise AssertionError(f"{method} {url} unexpectedly succeeded")


def main() -> None:
    try:
        subprocess.run(
            [*COMPOSE, "up", "-d", "--build", "--wait", "--wait-timeout", "240"], check=True
        )
        assert get_json("/readyz") == {"status": "ready"}
        revision = subprocess.run(
            [
                *COMPOSE,
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "axon",
                "-d",
                "axon",
                "-Atc",
                "SELECT version_num FROM alembic_version",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert revision, "migrations did not run"
        print(f"migrated to {revision}")
        # /admin/providers needs an admin token since B1; 401 proves it is mounted and guarded.
        assert http_error(API + "/admin/providers").code == 401
        assert get_json("/healthz", ENGINE) == {"status": "ok"}
        # Without vendor keys the engine must refuse calls, not pretend to answer them.
        refused = http_error(ENGINE + "/vobiz/answer", "POST")
        assert refused.code == 503
        assert json.load(refused)["error"] == "provider_not_configured"
        for image in ("axon-api:dev", "axon-engine:dev", "axon-worker:dev"):
            size = subprocess.run(
                ["docker", "image", "inspect", "--format", "{{.Size}}", image],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            assert int(size) < MAX_IMAGE_BYTES, f"{image} is {int(size) / 1e6:.0f} MB"
            print(f"{image}: {int(size) / 1e6:.0f} MB")
    except Exception:
        subprocess.run([*COMPOSE, "ps", "-a"], check=False)
        subprocess.run([*COMPOSE, "logs", "--tail", "50"], check=False)
        raise
    finally:
        if "--down" in sys.argv:
            subprocess.run([*COMPOSE, "down", "-v"], check=False)
    print("COMPOSE HEALTHY")


if __name__ == "__main__":
    main()
