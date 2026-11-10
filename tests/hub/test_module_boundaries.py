import importlib
import os
import pkgutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

import apps.hub
from apps.hub.core.base import Base
from tools.check import build_steps, run_step

ROOT = Path(__file__).resolve().parents[2]
INFRASTRUCTURE = {"core", "migrations"}
ENTRY_POINTS = {"__init__", "__main__", "main"}


def _contracts() -> dict[str, dict[str, Any]]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return {c["type"]: c for c in config["tool"]["importlinter"]["contracts"]}


def _hub_modules_on_disk() -> set[str]:
    hub = ROOT / "apps" / "hub"
    packages = {p.name for p in hub.iterdir() if (p / "__init__.py").is_file()} - INFRASTRUCTURE
    single_files = {p.stem for p in hub.glob("*.py")} - ENTRY_POINTS
    return {f"apps.hub.{name}" for name in packages | single_files}


def test_every_hub_module_is_covered_by_both_boundary_contracts() -> None:
    contracts = _contracts()
    layered = {m.strip() for layer in contracts["layers"]["layers"] for m in layer.split(":")}
    independent = set(contracts["independence"]["modules"])

    modules = _hub_modules_on_disk()
    assert modules, "expected at least one Hub module"
    assert modules - layered == set(), "add the module to the layers contract in pyproject.toml"
    assert modules - independent == set(), "add the module to the independence contract"


def test_gate_runs_module_boundaries_and_they_hold() -> None:
    (step,) = [s for s in build_steps() if s.name == "module boundaries"]
    assert run_step(step).status == "pass"


def _lint_fake_hub(tmp_path: Path, a_imports: str) -> int:
    """Run our real independence contract, renamed onto a throwaway two-module package."""
    contract = _contracts()["independence"]
    rename = {"apps.hub": "fakehub"}

    def renamed(s: str) -> str:
        for old, new in rename.items():
            s = s.replace(old, new)
        return s

    pkg = tmp_path / "fakehub"
    for name in ("a", "b"):
        (pkg / name).mkdir(parents=True)
        (pkg / name / "__init__.py").write_text("")
        (pkg / name / "service.py").write_text("")
        (pkg / name / "models.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "a" / "logic.py").write_text(f"import {a_imports}\n")

    ignores = "\n    ".join(renamed(i) for i in contract["ignore_imports"])
    (tmp_path / ".importlinter").write_text(
        "[importlinter]\nroot_package = fakehub\n\n"
        "[importlinter:contract:only-via-service]\n"
        f"name = {contract['name']}\ntype = independence\n"
        "modules =\n    fakehub.a\n    fakehub.b\n"
        f"ignore_imports =\n    {ignores}\n"
        f"unmatched_ignore_imports_alerting = {contract['unmatched_ignore_imports_alerting']}\n"
    )
    (step,) = [s for s in build_steps() if s.name == "module boundaries"]
    return subprocess.run(
        [step.argv[0], "--no-cache", "--config", str(tmp_path / ".importlinter")],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        check=False,
    ).returncode


@pytest.mark.parametrize(
    ("target", "expected_exit"),
    [("fakehub.b.models", 1), ("fakehub.b.service", 0)],
)
def test_independence_contract_allows_only_service_imports(
    tmp_path: Path, target: str, expected_exit: int
) -> None:
    assert _lint_fake_hub(tmp_path, target) == expected_exit


def test_every_mapped_entity_keeps_optimistic_locking() -> None:
    for info in pkgutil.walk_packages(apps.hub.__path__, "apps.hub."):
        if not info.name.startswith(("apps.hub.migrations", "apps.hub.__main__")):
            importlib.import_module(info.name)
    for mapper in Base.registry.mappers:
        assert mapper.version_id_col is not None, f"{mapper.class_.__name__} lost version_id_col"
