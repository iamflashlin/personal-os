# 0003 — D0 toolchain and dependencies

- Status: accepted
- Date: 2026-11-10

| Dependency | Where | Why | Alternative rejected |
|---|---|---|---|
| ruff 0.17 | uv `dev` | lint + format, one fast tool (HANDOFF §4.8) | flake8+black+isort: three tools |
| pytest 9.2 | uv `dev` | Python tests (HANDOFF §4.8) | — |
| pyright 1.1.414 | **pnpm** devDependency | type checker (HANDOFF §4.8). The PyPI `pyright` wrapper downloads Node packages at first run into a cache on `C:`; the npm package is locked in `pnpm-lock.yaml` and stored on `D:` | PyPI wrapper; basedpyright |
| typescript 7.0, vitest 5.1 | pnpm devDependencies | frontend type check + tests (HANDOFF §4.8). ESLint deferred to S4 when `apps/web` exists | ESLint now: nothing to lint yet |
| pywinauto 0.6.9, Pillow 13 | uv `desktop` group, `sys_platform == 'win32'` | UIA window verification + window screenshots (ADR 0002) | Windows-MCP: too broad, no audit (HANDOFF §5) |
| @playwright/mcp 0.0.84 | `.mcp.json` via npx | browser verification for Claude Code (HANDOFF §5) | `@latest`: unpinned |

`pnpm` itself is pinned through `packageManager: pnpm@12.18.0`; CI installs that exact
version via `pnpm/action-setup`. Python is pinned to 3.12 via `.python-version`;
`uv.lock` and `pnpm-lock.yaml` are committed and CI installs with `--locked` /
`--frozen-lockfile`.

Not added yet: import-linter (module-boundary check) — no Hub modules exist; T-0001
adds it and enables the `module boundaries` step in `tools/check.py`.
