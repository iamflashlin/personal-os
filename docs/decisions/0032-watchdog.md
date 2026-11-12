# 0032: Watchdog - the Hub task repeats every 5 minutes

Status: accepted (2026-11-11, the user: "都做")

## Context
The always-on Hub (ADR 0021) has two layers. A supervisor (`run-hub.ps1`) restarts the Hub
within 10 seconds. The task's RestartCount/RestartInterval settings only cover a task that
fails to launch or run; they never react to the exit code of a process that has ended (the
old comment in install-always-on.ps1 said otherwise). So once the supervisor itself is gone,
nothing starts it again until the next logon. On 2026-11-11 at about 17:30 both were stopped
with 0xC000013A (STATUS_CONTROL_C_EXIT, a console close or break signal), and the Hub stayed
down until the assistant started the task by hand. The cause of the signal was not found.

## Decision
- The logon trigger repeats every 5 minutes, with no end. `MultipleInstances IgnoreNew`
  leaves a running supervisor alone, so a check that finds the supervisor running does
  nothing. A dead one is started again.
- An update lock (`<data>\updating.lock`, `scripts/run/update-lock.ps1`) is held by
  update-hub.ps1 and install-always-on.ps1 while they replace the copy. The supervisor waits
  while it is held, before its first start and before every restart. The lock holds the
  updating script's process id. It counts only while that process runs, and never for more
  than 60 minutes, so a crashed update cannot keep the Hub down. A script frees only its own
  lock.
- The supervisor writes "supervisor started (pid N)" when it starts. The log then shows
  when the watchdog had to start it.

## Consequences
- The longest outage after an unexpected kill is about 5 minutes instead of "until the next
  logon".
- `stop-hub.ps1` on its own now stops the Hub for at most 5 minutes. To keep it stopped, run
  `uninstall-always-on.ps1`.
- The new trigger needs install-always-on.ps1 once. The user runs it, because the assistant's
  permission checks block registering a scheduled task. update-hub.ps1 still never changes
  the task.
- Ending the task by hand in Task Scheduler is also undone within 5 minutes.
- A copy rolled back to a commit from before T-0029 has a run-hub.ps1 that does not read the
  lock. While such a rollback is rebuilding, the watchdog may start it early. This can only
  happen after a later failed update or `install -Ref <old commit>`.
- install-always-on.ps1's `Restore-And-Fail` starts the task again without moving the copy
  back (unlike update-hub.ps1). With the watchdog, a half-built copy from a failed install is
  retried every 5 minutes until the install is run again. The install prints FAILED, and the
  user runs it by hand, so this is accepted for now.
