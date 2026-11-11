from pathlib import PurePosixPath, PureWindowsPath

from apps.desktop_agent.actions import Done, window_evidence
from apps.desktop_agent.controller import DesktopController
from packages.contracts.actions import ActionStatus, OpenFolderParams


def _folder_name(path: str) -> str:
    windows = PureWindowsPath(path)
    return windows.name if windows.is_absolute() else PurePosixPath(path).name


def run(params: OpenFolderParams, desktop: DesktopController, timeout_s: float) -> Done:
    code = desktop.which("code")
    if code is None:
        # Installing VS Code is the user's call; nothing is started.
        return Done(ActionStatus.needs_user, "VS Code's `code` command is not on PATH")
    desktop.spawn([code, "--new-window", params.path])
    name = _folder_name(params.path)
    window = desktop.wait_for_window(name, timeout_s)
    if window is None:
        return Done(ActionStatus.failed, f"no VS Code window for '{name}' within {timeout_s:g}s")
    return Done(
        ActionStatus.succeeded,
        "opened in VS Code",
        [window_evidence(window, f"a window title contains '{name}'")],
    )
