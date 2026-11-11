"""Action name -> handler. Its keys must equal the contract's ACTION_SPECS."""

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from apps.desktop_agent.actions import Done, open_folder, open_url
from apps.desktop_agent.controller import DesktopController
from packages.contracts.actions import ActionName

Handler = Callable[[Any, DesktopController, float], Done]

REGISTRY: Mapping[ActionName, Handler] = MappingProxyType(
    {
        ActionName.open_url: open_url.run,
        ActionName.open_folder_in_editor: open_folder.run,
    }
)
