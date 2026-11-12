"""Write course profiles (ADR 0040) from a local JSON file into the Hub.

Usage: uv run python scripts/academic/import_profiles.py <profiles.json> [--hub URL]

The file is a list of ProfileFields. Existing profiles are replaced (the Hub clears their
confirmation when the content changed); nothing is deleted. The file stays outside the repo.
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.contracts.academic import ProfileFields


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--hub", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    items = [ProfileFields.model_validate(x) for x in json.loads(args.path.read_text("utf-8"))]
    with httpx.Client(base_url=args.hub, timeout=30) as hub:
        for f in items:
            current = hub.get(f"/academic/profiles/{f.code}")
            version = current.json()["version"] if current.status_code == 200 else None
            r = hub.put(
                f"/academic/profiles/{f.code}",
                json={"fields": f.model_dump(mode="json"), "version": version},
            )
            print(f.code, r.status_code, "confirmed" if r.json().get("confirmed_at") else "")
            if r.status_code >= 400:
                print(r.text)
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
