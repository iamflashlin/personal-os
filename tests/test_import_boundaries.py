"""The Hub, the desktop agent and the shared contracts keep apart (ADR 0014).

Each case runs our real contract from pyproject.toml, renamed onto a throwaway package,
so a contract that silently stops matching anything fails here.
"""

import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

from tools.check import build_steps

ROOT = Path(__file__).resolve().parents[1]
APPS_APART = "hub and desktop agent share only contracts"
CONTRACTS_PURE = "contracts import no app"
# Namespace parents with no __init__.py, like `apps` and `packages`: with a regular parent
# package lint-imports exits 1 without reporting any contract.
RENAME = {
    "apps.hub": "fakeapps.hub",
    "apps.desktop_agent": "fakeapps.agent",
    "packages.contracts": "fakepkgs.contracts",
}


def _contract(name: str) -> dict[str, Any]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    (contract,) = [c for c in config["tool"]["importlinter"]["contracts"] if c["name"] == name]
    return contract


def _renamed(modules: list[str]) -> str:
    return "".join(f"\n    {RENAME[m]}" for m in modules)


def _lint(tmp_path: Path, importer: str, imported: str) -> str:
    """The lint report; raises if lint-imports failed without judging the contracts."""
    for package in RENAME.values():
        (tmp_path / package.replace(".", "/")).mkdir(parents=True)
        (tmp_path / package.replace(".", "/") / "__init__.py").write_text("")
    (tmp_path / importer.replace(".", "/") / "code.py").write_text(f"import {imported}\n")

    apart, pure = _contract(APPS_APART), _contract(CONTRACTS_PURE)
    (tmp_path / ".importlinter").write_text(
        f"[importlinter]\nroot_packages ={_renamed(list(RENAME))}\n\n"
        f"[importlinter:contract:apart]\nname = {apart['name']}\ntype = {apart['type']}\n"
        f"modules ={_renamed(apart['modules'])}\n\n"
        f"[importlinter:contract:pure]\nname = {pure['name']}\ntype = {pure['type']}\n"
        f"source_modules ={_renamed(pure['source_modules'])}\n"
        f"forbidden_modules ={_renamed(pure['forbidden_modules'])}\n"
    )
    (step,) = [s for s in build_steps() if s.name == "module boundaries"]
    done = subprocess.run(
        [step.argv[0], "--no-cache", "--config", str(tmp_path / ".importlinter")],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path), "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    assert "Contracts: " in done.stdout, done.stdout + done.stderr
    return done.stdout


@pytest.mark.parametrize(
    ("importer", "imported", "broken"),
    [
        ("apps.desktop_agent", "apps.hub", APPS_APART),
        ("apps.hub", "apps.desktop_agent", APPS_APART),
        ("packages.contracts", "apps.hub", CONTRACTS_PURE),
        ("packages.contracts", "apps.desktop_agent", CONTRACTS_PURE),
        ("apps.desktop_agent", "packages.contracts", None),
        ("apps.hub", "packages.contracts", None),
    ],
)
def test_only_contracts_cross_between_hub_and_agent(
    tmp_path: Path, importer: str, imported: str, broken: str | None
) -> None:
    report = _lint(tmp_path, RENAME[importer], RENAME[imported])
    if broken is None:
        assert "0 broken" in report, report
    else:
        assert f"{broken} BROKEN" in report, report
        assert "1 broken" in report, report
