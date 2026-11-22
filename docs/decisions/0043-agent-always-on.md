# 0043 - The always-on supervisor keeps the desktop agent running, opt-in

- Status: accepted (the user, 2026-11-22: "你不用到我的地方就直接开始做吧"). The switch
  itself is left to the user, see decision 3.
- Card: T-0063. Builds on ADR 0021 (always-on Hub) and ADR 0014-0016 (the agent).

## Context

开始学习 (ADR 0042) sends whitelisted actions to the desktop agent. The agent ran only
when started by hand, so every start said 「电脑助手没有连上」. On 2026-11-22 the plan asked
the user whether the agent should start with the computer; they were asleep, and said to
do whatever does not need them.

## Decisions

1. **The existing supervisor runs the agent too.** `run-hub.ps1` now loops every 2 s over
   two child processes, the Hub and the agent, instead of blocking on the Hub. Each one is
   restarted 10 s after it exits. The Hub keeps its old behaviour, logs and `hub.pid`. The
   agent gets `agent-run-*.log` files and `agent.pid`.
2. **Nothing new is registered with Windows.** No second scheduled task, no service, no
   Run key. The agent lives and dies with the "PersonalOS Hub" task the user installed
   (ADR 0021 decision 4 kept the right to register persistence with the user).
3. **Opt-in by a file the user's own command writes.** The agent runs only while
   `D:\dev\personal-os-data\agent.enabled` exists. `scripts/run/enable-agent.ps1` pairs
   the agent with the running Hub (one-time code; the token goes to Windows Credential
   Manager) and then writes the file. `-Disable` removes it, and the supervisor stops the
   agent within 2 s. Until the user runs it, the deployed change does nothing.
4. **Exits a restart cannot fix are held.** Exit 2 (not paired), 3 (token rejected) or 4
   (another agent replaced it) are logged as "needs pairing" and not retried until
   `agent.enabled` is written again. Otherwise a revoked device would be retried every
   10 s forever, and two agents would keep replacing each other.
5. **`stop-hub.ps1` stops the supervised agent by the same rules as the Hub:** uv only
   when its id is in `agent.pid`, python only when it runs from the runtime copy. A
   developer's own agent elsewhere is never touched.

## Consequences

- `update-hub.ps1` restarts the supervisor and so the agent. `run-hub.ps1`'s parameters
  are unchanged, so no re-install is needed.
- After the update that deploys this, the user runs `enable-agent.ps1` once. From then on
  the agent starts at logon with the Hub.

## 未验证

A real sign-out and sign-in with the agent enabled (the same open item as ADR 0021).
Spike (≤ 5 min): after enabling, sign out and in, then open 课程 and press 开始学习.
