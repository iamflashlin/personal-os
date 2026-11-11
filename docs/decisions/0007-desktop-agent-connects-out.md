# 0007 — The desktop agent connects out to the Hub

- Status: accepted. Not built yet: `apps/desktop_agent` does not exist.
- Date: 2026-11-10
- Source: HANDOFF §3 items 2, 3; §4; §4.5. Recorded by D0-06, after ADRs 0008 and 0009.

## Context

In V0.1 the Hub runs on the same laptop as the desktop agent. The laptop sleeps when
its lid closes, so a phone command can arrive while nothing can act on it. Later the
Hub should move to a small always-on server while the agent stays on the PC. A home PC
behind NAT should not open inbound ports. The phone must also be able to show that the
PC is offline.

## Decision

- The Hub and the desktop agent are separate processes, even on one machine. They talk
  over the network, not through in-process calls.
- The agent opens a long-lived WebSocket to the Hub and sends heartbeats. The Hub never
  connects to the agent.
- The Hub sends `ActionRequest` down the socket. The agent sends `ActionResult` with
  evidence back up. Both types live in `packages/contracts` (HANDOFF §4.2).
- The Hub address is configuration. Moving the Hub to a server changes config only.
- When no agent is connected, the Hub queues the command (SQLite job table) and tells
  the user. The PWA shows "PC offline".
- The agent authenticates with a device token obtained by one-time pairing. The Hub can
  revoke the token (HANDOFF §4.5).
- Network: Tailscale. The Hub listens only on loopback (today's default, `127.0.0.1`)
  and the Tailscale interface.
- The agent holds no durable state. Runs, steps and evidence are stored by the Hub.

## Alternatives considered

- The Hub calls an HTTP server on the agent: needs an inbound port and a reachable
  address on the PC, and breaks when the Hub moves off the PC.
- The agent polls the Hub over HTTP: simpler, but adds latency or load, and offline
  detection is coarser. This is the fallback if WebSocket proves unreliable.
- A message broker (MQTT, Redis): one more service to run and secure.
- Agent code inside the Hub process: fewest parts, but it ties the Hub to the desktop,
  so the Hub cannot move to a server.

## Consequences

- The agent never listens on a port. In V0.1 the Hub on the PC listens only on loopback
  and the Tailscale interface (no public port). After the Hub moves, the PC listens on
  nothing.
- The Hub needs a connection registry, a heartbeat timeout and a queue for offline
  commands.
- The agent needs reconnect with backoff. A request can arrive twice after a reconnect,
  so `idempotency_key` must make execution at-most-once.
- In V0.1 the PC runs two processes.
- Unverified (未验证): that a WebSocket over Tailscale survives laptop sleep and resume
  and reconnects within a few seconds, and whether Windows Firewall prompts when the Hub
  binds to the Tailscale interface. Spike (half a day at most): a minimal FastAPI
  WebSocket server and a Python client with heartbeat and backoff; sleep the laptop for
  two minutes, then log reconnect time, lost messages and any firewall prompt.
