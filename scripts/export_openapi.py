"""Write the API's OpenAPI document to packages/contracts/openapi.json for the web client.

Usage: uv run python scripts/export_openapi.py
CI runs it and fails if the committed file (or the TS types generated from it) is stale.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "services/api"))

from app.main import app  # noqa: E402

out = ROOT / "packages/contracts/openapi.json"
out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"wrote {out.relative_to(ROOT)}")
