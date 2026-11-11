# 进度报告

> 由 `uv run python -m tools.report --today 2026-11-10` 生成，请不要手改。进度只按“合并进 main 的、验证过的改动”计算。
> 统计依据：origin/main @ e87dbea（如果刚在 GitHub 上合并过 PR，先运行 `git fetch` 再生成）。

## 现在做到哪

共 16 张任务卡：已完成 5，进行中 1，待审核 5，卡住 3，未开始 2。

### 已完成

- **D0-01** Repository skeleton, uv + pnpm, tools.check quality gate, CI
- **D0-03** CLAUDE.md, permission rules, architect/reviewer/tester subagents, .mcp.json
- **D0-05** Spike - open Notepad, screenshot, read title via pywinauto, close
- **T-0001** Hub skeleton - FastAPI app, settings, SQLite (WAL) + Alembic, base model, boundary check
- **T-0002** Goal / Project / Task / Workspace CRUD API with audit log

### 进行中

- **T-0005** Second brain v0 - Memory entries with provenance, correction, expiry and full-text search

### 待审核

- **D0-06** ARCHITECTURE.md and ADRs for modular monolith, SQLite, agent-initiated connection
- **D0-07** tools/report.py generates docs/progress.md from task cards and git log
- **D0-08** Record the product vision, propose a realigned roadmap, and housekeeping
- **T-0003** pos export / pos import v0 with round-trip migration test
- **T-0004** Minimal web UI - list goals/projects/tasks, create a task, confirm a task done

### 卡住了

- **T-0006** Action contract and Hub side of the desktop agent link - pairing, token, WebSocket, heartbeat, idempotent dispatch
- **T-0007** Desktop agent core - connect out, reconnect with backoff, whitelist registry, at-most-once executor
- **T-0008** WindowsAdapter and real local verification - open a test URL and a temp folder, verify windows, prove one execution per key

## 下一步

前置任务都已完成、可以马上开始的卡：

- **D0-02** Reconcile pstack poteto-mode principles with project rules

还在等前置任务的卡：

- **D0-04** Project skills (task-card, evidence, verify-hub, verify-desktop-agent) and PR template（等 D0-02）

## 本周合并（2026-11-09 至 2026-11-15）

本周合并了 5 张任务卡：D0-01, D0-03, D0-05, T-0001, T-0002。

- 2026-11-10 feat(hub): goal/project/task/workspace CRUD with audit log (T-0002) (#3)
- 2026-11-10 feat(hub): add Hub skeleton with migrated SQLite and boundary checks (T-0001) (#2)
- 2026-11-10 chore: bootstrap D0 dev factory (D0-01, D0-03, D0-05) (#1)

## 返工

以 `fix:` 开头、修的是之前已经合并过的任务卡的提交：

- （没有）

## 我能看到什么

**Hub 的接口文档页：能看到并试用所有接口**

1. `uv run python -m apps.hub`
2. 浏览器打开 http://127.0.0.1:8765/docs
