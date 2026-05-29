# Setup Guide

## What you need first

**LM Studio** must be installed manually — [lmstudio.ai](https://lmstudio.ai). It runs the local LLM that all agents use. Everything else is handled by the setup script.

---

## 1. Run setup.sh

```sh
cd Orchestrator
bash setup.sh
```

This installs [uv](https://github.com/astral-sh/uv) (a fast Python package manager) if it isn't already present, then uses it to:

- Download **Python 3.11** into uv's own cache — your existing Python installations are not touched
- Create an isolated **`.venv`** in the project directory
- Install all required packages (`open-interpreter`, `tiktoken`)

Running it again is safe. The `.venv` is kept if it already exists, and packages are upgraded.

---

## 2. Configure LM Studio

1. Open LM Studio and download a main pipeline model. The system was built with **Qwen3.5-35b-a3b**; any capable instruction-following model in the 7–35B range should work.
2. If you plan to use `--security medium` or `--security high`, also download **mistralai/ministral-3-3b** as the dedicated security model.
3. Start the **local server** (default address: `http://127.0.0.1:1234/v1`). The orchestrator auto-detects the loaded model at startup.

---

## 3. Verify the setup

```sh
# Check that agents load correctly
./orchestrator --list-agents

# Quick smoke test (no GitHub access needed)
./orchestrator --task "Explain what a Bloom filter is in one sentence"
```

---

## 4. Run the release pipeline

```sh
# See what commits would be processed (no LLM calls, no writes)
./ReleaseNotes/release_pipeline --dry-run

# Process new commits for the default repo
./ReleaseNotes/release_pipeline

# Different repo, rolling 24-hour window, medium security
./ReleaseNotes/release_pipeline --repo owner/repo --today --security medium

# Work through commit history one day at a time
./ReleaseNotes/release_pipeline --backlog --limit 10
```

Output is written to `ReleaseNotes/output/<owner_repo>/` — one directory per repository, gitignored.

---

## GitHub API rate limits

Unauthenticated requests are capped at 60/hour. For large repos or frequent runs, pass a token:

```sh
./ReleaseNotes/release_pipeline --token ghp_yourtoken
```

Generate one at **github.com/settings/tokens** — no scopes needed for public repos.

---

## Troubleshooting

**`Error: .venv not found`** — Run `bash setup.sh` from the `Orchestrator/` directory.

**`LM Studio unreachable — using default`** — LM Studio isn't running or its server isn't started. Open LM Studio and enable the local server.

**GitHub 403 rate limit** — Use `--token` (see above) or wait for the rate limit window to reset (1 hour).
