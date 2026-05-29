# Orchestrator

A multi-agent LLM pipeline that delegates tasks to specialized agents via a local model (LM Studio).

## Structure

```
Orchestrator/
├── orchestrator.py        Main orchestrator — plans, executes, and synthesizes via local LLM
├── orchestrator           Shell wrapper (run without specifying python3 or .py)
├── agents/                Agent definitions (JSON). Each describes a role and system prompt.
│   ├── code_reader.json   Fetches a GitHub commit and saves it to the local database
│   ├── release_writer.json  Reads commit data and writes a release note entry
│   ├── release_editor.json  Validates a written release note against the original commit
│   └── writer.json        General-purpose prose writer
├── tools/
│   └── security_check.py  Standalone LLM classifier for prompt injection detection
├── ReleaseNotes/          Pipeline: automated release notes from GitHub commits (see below)
└── ShoppingAssistant/     Pipeline: interactive product research and comparison report (see below)
```

## ReleaseNotes

Automates release note generation for a GitHub repository.

```
ReleaseNotes/
├── release_pipeline.py    Fetches new commits and runs the orchestrator for each one
├── release_pipeline       Shell wrapper
├── how-it-works.md        Detailed description of the pipeline design and results
├── tools/
│   ├── release_tools.py   DB and file I/O shared by all release note agents
│   ├── fetch_commit_data.py   CLI — look up a commit from the local database
│   └── write_release_entry.py CLI — manually write a release note entry
└── output/                Per-repo output (gitignored, created at runtime)
    └── owner_repo/
        ├── release_data.db        SQLite database of fetched commits
        ├── RELEASE_NOTES.md       Generated release notes file
        └── orchestrator_stats.jsonl  Token and timing stats per run
```

## ShoppingAssistant

Interactively collects what a user wants to buy, searches the web, researches individual products, and produces a verified HTML comparison report with purchase links.

```
ShoppingAssistant/
├── shopping_pipeline.py   Main pipeline: Q&A → search → scout → research → report → HTML
├── shopping_pipeline      Shell wrapper
├── agents/
│   ├── question_asker.json    Collects and formalises purchase requirements via Q&A
│   ├── product_scout.json     Extracts named product models from search result snippets
│   ├── product_researcher.json  Reads queued search results and saves a full product record
│   ├── report_author.json     Writes a structured JSON comparison report from product data
│   ├── accuracy_checker.json  Validates every report claim against raw research snippets
│   └── report_presenter.json  Renders the verified report as a self-contained HTML file
├── tools/
│   ├── shopping_tools.py  DB ops (session, products, report) + DuckDuckGo search
│   └── …                  CLI helpers for debugging (fetch_requirements, fetch_products, …)
├── test_responses/
│   └── coffee-grinder.json  Pre-filled answers for automated test runs
└── output/                Per-project output (gitignored, created at runtime)
    └── coffee-grinder/
        ├── shopping_data.db         SQLite: session, products, report tables
        ├── SHOPPING_REPORT.json     Verified report data snapshot
        ├── SHOPPING_REPORT.html     Self-contained comparison page with buy links
        └── orchestrator_stats.jsonl Token and timing stats per run
```

## Setup

Run `bash setup.sh` to install Python 3.11 (via Homebrew), create a `.venv`, and install dependencies. See **SETUP.md** for full instructions including LM Studio configuration.

## Usage

```sh
# Run the release note pipeline (defaults to geoff-codes-things/scripts)
./ReleaseNotes/release_pipeline

# Different repo, limit to 5 commits, medium security
./ReleaseNotes/release_pipeline --repo owner/repo --limit 5 --security medium

# Process only the last 24 hours (rolling window, no backlog state)
./ReleaseNotes/release_pipeline --today

# Work through history one day at a time, newest first (saves position between runs)
./ReleaseNotes/release_pipeline --backlog --limit 10

# Run the shopping assistant (interactive prompts)
./ShoppingAssistant/shopping_pipeline --name my-search

# Run with pre-filled answers to skip interactive prompts
./ShoppingAssistant/shopping_pipeline --name coffee-grinder --responses ShoppingAssistant/test_responses/coffee-grinder.json

# Reset a project and start over
./ShoppingAssistant/shopping_pipeline --name coffee-grinder --reset

# Use the orchestrator directly for any task
./orchestrator --task "Explain what a Bloom filter is"
```

## Security levels

| Flag | Behavior |
|------|----------|
| `--security low` (default) | Regex guard only |
| `--security medium` | + LLM check on user task and external-data agent responses |
| `--security high` | LLM check at every step |

LLM security checks use `mistralai/ministral-3-3b` by default (`--security-model` to override).
