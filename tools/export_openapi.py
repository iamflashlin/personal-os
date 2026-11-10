"""Write the Hub's OpenAPI schema to packages/contracts/openapi.json.

uv run python -m tools.export_openapi          # rewrite the file
uv run python -m tools.export_openapi --check  # exit 1 if the file is stale
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from apps.hub.core.settings import Settings
from apps.hub.main import create_app

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "packages" / "contracts" / "openapi.json"


def openapi_json() -> str:
    """The schema as committed. Building the app touches no files; startup never runs."""
    schema = create_app(Settings()).openapi()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    current = openapi_json()
    if args.check:
        committed = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if committed != current:
            print(f"STALE: {OUT.relative_to(ROOT)}; run `uv run python -m tools.export_openapi`")
            return 1
        print("openapi.json is up to date")
        return 0
    OUT.write_text(current, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
