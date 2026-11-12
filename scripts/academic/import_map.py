"""Write a course knowledge map (ADR 0041) from a local JSON file into the Hub.

Usage: uv run python scripts/academic/import_map.py <map.json> [--hub URL]

The file lists chapters and sections; a section may nest its concepts as
[key, title, title_zh, page] or [key, title, title_zh, page, [prerequisites]].
Prerequisites are the assistant's (prereq_origin ai) and items are the teacher's (origin
teacher) unless an entry says otherwise. The map replaces the course's previous one; the
user's mastery is kept. The file stays outside the repo.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.contracts.course_map import MapIn


def flatten(raw: dict[str, Any]) -> MapIn:
    concepts: list[dict[str, Any]] = []
    for c in raw["concepts"]:
        nested = c.get("concepts") or []
        concepts.append(
            {
                "key": c["key"],
                "kind": c["kind"],
                "parent": c.get("parent", ""),
                "title": c["title"],
                "title_zh": c.get("title_zh", ""),
                "page": c.get("page"),
                "prereq": c.get("prereq", []),
                "prereq_origin": c.get("prereq_origin", "ai"),
                "origin": c.get("origin", "teacher"),
            }
        )
        for entry in nested:
            key, title, zh, page = entry[:4]
            concepts.append(
                {
                    "key": key,
                    "kind": "concept",
                    "parent": c["key"],
                    "title": title,
                    "title_zh": zh,
                    "page": page,
                    "prereq": entry[4] if len(entry) > 4 else [],
                }
            )
    return MapIn.model_validate(
        {
            "course_code": raw["course_code"],
            "material": raw.get("material", ""),
            "note": raw.get("note", ""),
            "concepts": concepts,
            "exams": raw.get("exams", []),
            "exam_checklist": raw.get("exam_checklist", []),
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--hub", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    course = flatten(json.loads(args.path.read_text("utf-8")))
    with httpx.Client(base_url=args.hub, timeout=30) as hub:
        r = hub.put(f"/academic/maps/{course.course_code}", json=course.model_dump(mode="json"))
        print(course.course_code, len(course.concepts), "concepts", r.status_code)
        if r.status_code >= 400:
            print(r.text)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
