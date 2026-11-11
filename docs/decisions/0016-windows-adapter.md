# 0016 — Windows adapter: finding, capturing and closing windows

- Status: accepted (decided by Claude under ADR 0014, which the user accepted on
  2026-11-10).
- Date: 2026-11-10
- Card: T-0008. ADR 0002 (touch only what we created), ADR 0014 D5 (screenshots of our own
  page only), ADR 0015 (agent core).

## Spike results on this PC (Windows 11, default browser Microsoft Edge)

| # | Question | Result |
|---|---|---|
| R2 | Does `PrintWindow(PW_RENDERFULLCONTENT)` return real pixels of the browser page? | **Yes.** The crop to the page's UIA Document control was 100% our page's colour (`scripts/verify/spike_printwindow.py`, `open_url_page.png`). No tab strip, address bar or other tab titles are in the crop. **Covered too:** with our own topmost, never-activated window placed over the whole Edge window, the crop was still 100% our page. |
| R3 | Default browser and title format; can our page close itself? | Edge (`MSEdgeHTM`). `os.startfile` opened a new tab in the user's existing window, and the window title became `<our title> 和另外 N 个页面 - 个人 - Microsoft Edge`, so a substring match on our unique title works. `window.close()` from the page closed that tab: the title disappeared within the wait. |
| R4 | `code` on PATH, VS Code window titles | VS Code is installed at `D:\Apps\VSCode` (user setup), with `bin` on the user PATH. A first search missed it: the search looked only in the default install folders, and the shell running it had inherited a PATH from before the install. With VS Code not running, `code --new-window <folder>` opened one window titled `<folder name> - Visual Studio Code`. No previous windows were restored, and closing it left no VS Code window open. |
| R5 | UIA from a worker thread | Window search uses `win32gui` and needs no COM. UIA is only used for the page capture, which runs in the verify script's main thread. COM in the agent's desktop thread is not needed yet. |
| — | Foreground | Our code never focuses a window. Edge itself came to the front when the link opened (its own behaviour on a ShellExecute'd URL). HANDOFF §8.3's foreground risk therefore comes from the browser, not from the agent. |

## Decisions

1. **Finding windows:** `EnumWindows` over visible top-level windows, matched by substring
   of a title the caller chooses. No focus, no clicks, no keystrokes. Each action first
   remembers every (window, title) pair already open, and only a window that is new, or
   whose title changed (a browser's new tab), counts as the action's evidence. An
   existing tab that already showed the title does not.
2. **Screenshots** are taken by the verify script, not by the agent. Steps:
   - Find the UIA Document named after our page's title. This is our tab, never simply
     the first Document.
   - PrintWindow into memory, then re-read the window title; if the user switched tabs
     meanwhile, drop the capture.
   - Crop, check the crop is our page's colour, and only then save it.

   So a wrong crop never reaches the disk. Per-monitor-v2 DPI awareness is set just
   before capturing, so window and UIA rectangles agree on scaled displays. The agent's
   evidence stays the window title and process id, so the contract is unchanged.
3. **Closing:** `WindowsAdapter.close()` posts `WM_CLOSE`. Only the verify script calls it,
   and only on the VS Code window it opened for its own temp folder. Our browser page
   closes itself.
4. **Imports:** `pywin32` (now declared, as ADR 0014 D1 decided), `pywinauto` and
   `pillow` exist only on Windows. On other platforms the adapter raises
   `ModuleNotFoundError` for itself, so `load_controller` falls back instead of crashing.
   The adapter, its tests and the verify scripts carry file-level pyright pragmas.
   `pnpm exec pyright --pythonplatform Linux` passes locally, the same check the Ubuntu
   CI runner makes.
5. **Follow-up (outside this card's paths):** `open_folder_in_editor` waits for the folder
   name. Matching the `- Visual Studio Code` title suffix as well would make it stricter;
   do it when VS Code can be verified on this PC.

## VS Code

The user pointed out that VS Code was installed (2026-11-10). With its `bin` folder on
PATH, `scripts/verify/desktop_agent.py` passed in full, including `open_folder_in_editor`.
A process started from an older environment still lacks that PATH entry; the agent then
answers `needs_user`, which is the designed behaviour, not a failure.
