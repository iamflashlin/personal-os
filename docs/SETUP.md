# Setting up a new machine

Prerequisites (HANDOFF §9): git, gh (logged in), Node.js ≥ 24, pnpm, uv, Claude Code,
VS Code (`code` on PATH).

## Keep caches off a small system drive (this laptop: C: has ~11 GB free)

These are per-machine, **not** in the repo (CI runners have no `D:\`):

- `UV_CACHE_DIR=D:\dev-cache\uv` (user environment variable)
- `PLAYWRIGHT_BROWSERS_PATH=D:\dev-cache\ms-playwright` (user environment variable)
- npm cache: `npm config set cache D:\dev-cache\npm`
- pnpm store: `pnpm config set store-dir D:\dev-cache\pnpm-store` — verify with
  `pnpm store path` (should print a path under `D:\dev-cache\pnpm-store`)

## Clone and install

    git clone https://github.com/iamflashlin/personal-os.git D:\dev\personal-os
    cd D:\dev\personal-os
    git config core.hooksPath .githooks
    uv sync
    pnpm install
    uv run python -m tools.check

`core.hooksPath` enables `.githooks/pre-push`, which blocks direct pushes to `main`.

## Claude Code

Start `claude` in the repo and trust the folder; it will offer the pstack plugin from
`.claude/settings.json` and ask to approve the `playwright` MCP server. Then run
`/pstack:setup-pstack` (writes `~/.claude/rules/pstack-models.md`, which is per-user).
