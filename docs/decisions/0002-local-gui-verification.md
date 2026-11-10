# 0002 — Real GUI verification on the local Windows machine (D0-05)

- Status: accepted
- Date: 2026-11-10

## Question

Can a script on this laptop open a desktop app, find its window through UI Automation,
read its title, screenshot it, close it, and confirm it closed? This is the basis of every
`verify()` in the desktop agent (HANDOFF §4.2) and of `scripts/verify/*`.

## Experiment

`scripts/verify/spike_notepad.py` (pywinauto 0.6.9, UIA backend; Pillow `ImageGrab`).
Run: `uv run python scripts/verify/spike_notepad.py` → exit 0, `result.json`:
window appeared, title `pos-spike-notepad.txt - Notepad`, 8 KB screenshot of the document
control only, window gone after close. Total ≈1.5 s. With Notepad already open the script
refuses (exit 2, `refuse.log`). Evidence: `.evidence/D0-05/`.

## Findings

1. **Works.** pywinauto UIA can find, read, focus, and close a Win11 packaged app window
   from an unelevated shell; Claude Code can run it directly (no sandbox).
2. **Track windows, not PIDs.** Win11 `notepad.exe` is a launcher stub that hands off to
   the packaged app process, so the PID from `Popen` is useless. Match windows by title
   (plus class name) instead.
3. **Session restore leaks private content.** The first attempt launched a blank Notepad;
   Win11 restored a previous tab and the screenshot captured the user's own file. That
   evidence was deleted immediately. Fix: open a marker file we created and require the
   marker in the title. A second attempt captured `win.rectangle()`: the restored
   tab's *name*, the account avatar, and slivers of windows behind Notepad (the rectangle
   includes the invisible DWM resize border) were still visible — reviewer caught it,
   evidence deleted. Rule for all verify scripts: act only on windows/files the script
   created, and capture only the content control that shows the script's own data
   (here the UIA `Document`), never the window rectangle, tab strip or full screen.
4. **Closing a window closes the user's tabs too.** If a Notepad window is already open,
   our file opens as a tab in *the user's* window and `close()` would close it. The
   script therefore refuses to run when any Notepad window exists; the window it closes
   is one it created (restored tabs inside it are kept by Notepad's session restore).
   S2's verify step must close only what it opened, or not close at all.
5. pywinauto 0.6.9 emits a `SyntaxWarning` on Python 3.12 (invalid escape in its
   source). Harmless; silence with `PYTHONWARNINGS=ignore::SyntaxWarning` if noisy.
   pywinauto releases are infrequent — re-evaluate if it breaks on a future Python.

## Decision

Use pywinauto (UIA) as the window-verification library for the desktop agent (as
HANDOFF §5 planned), with the rules in findings 2–4. Windows-only deps live in the
`desktop` dependency group with `sys_platform == 'win32'` markers, so ubuntu CI skips them.
