"""Guard for docs/lessons.md (2026-11-10): `with sqlite3.connect(...)` does not close.

The check walks the syntax tree, so comments and strings never match, and every form of
`with` is covered: several items on one line, the parenthesised multi-line form, and
`connect` imported from sqlite3.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("apps", "packages", "scripts", "tests", "tools")


def _connect_names(tree: ast.Module) -> set[str]:
    """Bare names bound to sqlite3.connect by `from sqlite3 import connect [as x]`."""
    return {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "sqlite3"
        for alias in node.names
        if alias.name == "connect"
    }


def _is_connect_call(expr: ast.expr, bare_names: set[str]) -> bool:
    if not isinstance(expr, ast.Call):
        return False
    func = expr.func
    if isinstance(func, ast.Attribute):
        return (
            func.attr == "connect"
            and isinstance(func.value, ast.Name)
            and (func.value.id == "sqlite3")
        )
    return isinstance(func, ast.Name) and func.id in bare_names


def unclosed_connects(source: str) -> list[int]:
    """Line numbers where a `with` item is a bare sqlite3 connect call."""
    tree = ast.parse(source)
    bare = _connect_names(tree)
    return sorted(
        item.context_expr.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.With | ast.AsyncWith)
        for item in node.items
        if _is_connect_call(item.context_expr, bare)
    )


@pytest.mark.parametrize(
    ("source", "lines"),
    [
        ("import sqlite3\nwith sqlite3.connect('x') as c:\n    pass\n", [2]),
        ("import sqlite3\nwith  sqlite3.connect( 'x' ):\n    pass\n", [2]),
        ("import sqlite3\nwith open('a') as f, sqlite3.connect('x') as c:\n    pass\n", [2]),
        ("import sqlite3\nwith (\n    sqlite3.connect('x') as c,\n):\n    pass\n", [3]),
        ("from sqlite3 import connect\nwith connect('x'):\n    pass\n", [2]),
        ("from sqlite3 import connect as db\nwith db('x'):\n    pass\n", [2]),
        (
            "import sqlite3\nfrom contextlib import closing\n"
            "with closing(sqlite3.connect('x')) as c:\n    pass\n",
            [],
        ),
        ("# with sqlite3.connect('x') as c:\nx = 'with sqlite3.connect(p) as c:'\n", []),
        ("def connect(p): ...\nwith connect('x'):\n    pass\n", []),
    ],
)
def test_detector(source: str, lines: list[int]) -> None:
    assert unclosed_connects(source) == lines


def test_sqlite_connections_are_closed_explicitly() -> None:
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{line}"
        for folder in SCANNED
        for path in sorted((ROOT / folder).rglob("*.py"))
        if "node_modules" not in path.parts
        for line in unclosed_connects(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        "`with sqlite3.connect(...)` commits but never closes the connection, which locks "
        f"the file on Windows; use `with closing(sqlite3.connect(...))` instead: {offenders}"
    )
