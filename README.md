# ai-agent-orchestration-config

Version-controlled AI-tooling instruction system for Claude Code, Gemini CLI, and Codex:
routers, shared instruction docs (`ai-instructions/`), project templates, coordination tools,
hooks, and scrubbed settings. **No credentials are stored here** (see `.gitignore` + `scripts/guard-secrets.ps1`).

## Layout
- `claude/` `gemini/` `codex/` — per-tool router, scrubbed settings, hooks
- `ai-instructions/` — the 7 indexed instruction docs + `templates/` + `tools/`
- `sync-manifest.txt` — maps repo paths <-> home paths (one source of truth)
- `scripts/` — `deploy.ps1`, `capture.ps1`, `guard-secrets.ps1`, `install-hooks.ps1`

## New machine
1. `gh repo clone getconversationalai/ai-agent-orchestration-config c:/dev/ai-agent-orchestration-config`
2. `cd c:/dev/ai-agent-orchestration-config`
3. `./scripts/install-hooks.ps1`
4. `./scripts/deploy.ps1 -WhatIf`  (preview), then `./scripts/deploy.ps1`

## Ongoing (after editing live instruction files)
1. `./scripts/capture.ps1`  (pull live edits into the repo)
2. `git add -A`
3. `git commit -m "..."`  (pre-commit secret scan runs automatically)
4. `git push`

## Pushed a change from the repo side instead?
Run `./scripts/deploy.ps1` to push it back out to the live files.
