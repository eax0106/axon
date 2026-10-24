"""Start the Docker Compose stack and prove it works. Prints COMPOSE HEALTHY on success.

Usage: uv run python scripts/compose_smoke.py [--down]
"""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

COMPOSE = ["docker", "compose", "-f", str(Path(__file__).parents[1] / "deploy/docker-compose.yml")]
API = f"http://localhost:{os.environ.get('AXON_API_PORT', '8000')}"
MAX_IMAGE_BYTES = 1_000_000_000


def get_json(path: str) -> Any:
    with urllib.request.urlopen(API + path, timeout=5) as response:
        return json.load(response)


def main() -> None:
    try:
        subprocess.run(
            [*COMPOSE, "up", "-d", "--build", "--wait", "--wait-timeout", "240"], check=True
        )
        assert get_json("/readyz") == {"status": "ready"}
        providers = get_json("/admin/providers")["providers"]
        assert providers and {p["status"] for p in providers} <= {
            "configured",
            "missing_key",
            "unhealthy",
        }
        for image in ("axon-api:dev", "axon-worker:dev"):
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
