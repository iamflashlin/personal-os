"""Versioned prompts in `prompts/<name>.v<N>.toml` (HANDOFF §4.4).

A file has two strings, `system` and `user`. `user` is a `string.Template` whose `$names`
are filled verbatim; values are never parsed again, so email text cannot inject fields.
"""

import hashlib
import string
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from apps.hub.core.settings import REPO_ROOT

PROMPTS_DIR = REPO_ROOT / "prompts"


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    system: str
    user: str
    sha256: str

    def render(self, variables: Mapping[str, str]) -> str:
        return string.Template(self.user).substitute(variables)


def load_prompt(name: str, version: int, root: Path = PROMPTS_DIR) -> Prompt:
    path = root / f"{name}.v{version}.toml"
    raw = path.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    system, user = data.get("system"), data.get("user")
    if not isinstance(system, str) or not isinstance(user, str):
        raise ValueError(f"{path.name} needs string fields 'system' and 'user'")
    return Prompt(name, version, system, user, hashlib.sha256(raw).hexdigest())
