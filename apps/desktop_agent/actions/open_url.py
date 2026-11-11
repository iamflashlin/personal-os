from apps.desktop_agent.actions import Done, window_evidence
from apps.desktop_agent.controller import DesktopController
from packages.contracts.actions import ActionStatus, OpenUrlParams


def run(params: OpenUrlParams, desktop: DesktopController, timeout_s: float) -> Done:
    desktop.open_url(str(params.url))
    window = desktop.wait_for_window(params.expect_title_contains, timeout_s)
    if window is None:
        return Done(
            ActionStatus.failed,
            f"no window titled '{params.expect_title_contains}' appeared within {timeout_s:g}s",
        )
    return Done(
        ActionStatus.succeeded,
        "opened",
        [window_evidence(window, f"a window title contains '{params.expect_title_contains}'")],
    )
