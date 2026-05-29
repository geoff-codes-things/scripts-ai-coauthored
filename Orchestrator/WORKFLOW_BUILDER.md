# Orchestrator Workflow Builder Reference

This document is structured in three zones. Zone A is always needed. Zones B and C are situational — load them when designing or debugging.

---

## Zone A — Essential

Everything required to build a new workflow from scratch.

### Invocation

```bash
python orchestrator.py --task "YOUR TASK HERE" [options]
```

| Flag | Default | Effect |
|---|---|---|
| `--agents-dir PATH` | `./agents` | Directory with agent JSON files |
| `--no-synthesis` | off | Skip synthesis LLM call; return last agent result directly |
| `--loop` | off | Cache plan template after first run; resolve via Ministral (~0.7s vs ~8s) |
| `--security low\|medium\|high` | `low` | Injection detection level |
| `--stats-path PATH` | `./orchestrator_stats.jsonl` | Stats log location |
| `--list-agents` | — | Print loaded agents and exit |
| `-v` | off | Verbose output with timestamps |

### Agent JSON format

Agents live in `agents/` as `.json` files. All files are loaded automatically at startup. Add a file — it appears at the next run, no code changes needed.

```json
{
  "name": "agent_name",
  "description": "One sentence: what this agent does and when to use it.",
  "system_prompt": "Complete instructions for the LLM when acting as this agent.",
  "auto_run": true,
  "external_data": false
}
```

| Field | Required | Notes |
|---|---|---|
| `name` | yes | Identifier used in plans |
| `description` | yes | Planner reads this to decide routing. Precision matters: "Fetches weather from NOAA API and returns current conditions as JSON" beats "gets weather". Must also match the pipeline's task strings — if the task says "read the queued file" but the description says "for a specific named product", the planner invents a step to identify the product first |
| `system_prompt` | yes | Most important field. The complete instruction set the LLM sees when acting as this agent |
| `auto_run` | yes | `true` = agent can execute code; `false` = text-only output |
| `external_data` | no | `true` = agent fetches untrusted data from outside the system (APIs, web pages). Enables targeted security checks at `--security medium` or `high` |

### Plan format

The orchestrator LLM produces a JSON plan. Steps run sequentially — later steps can depend on earlier ones (via shared files or database state).

```json
{
  "plan": [
    {"agent": "agent_name", "task": "specific subtask for this agent"},
    {"agent": "another_agent", "task": "this step depends on output from the previous one"}
  ]
}
```

On-the-fly agent (when no existing agent fits a step):
```json
{
  "agent": "__new__",
  "name": "slug",
  "description": "one line",
  "system_prompt": "full instructions",
  "auto_run": false,
  "task": "subtask"
}
```

After the run, the orchestrator prompts to save any on-the-fly agents to disk.

### Agent communication protocol

**Agents do not share memory.** The only channel between agents is files on disk (SQLite database, output files). Do not rely on an agent's text response to pass data to the next step.

**Failure signal.** If an agent cannot complete its task due to missing information, it must respond with:
```
NEEDS_INPUT: <description of what is missing>
```
The orchestrator detects this, marks the step as `[STEP FAILED]`, and continues to synthesis, which reports the failure.

**Short-circuit signal.** If an agent determines that remaining steps should be skipped (e.g., a commit doesn't need a release note):
```
SKIP_REMAINING: <brief reason>
```
The orchestrator marks all subsequent steps as `(skipped — <reason>)` and stops execution immediately.

### SHA injection

The orchestrator automatically extracts the first commit SHA (40-char or 7-char) from the original task text and appends it to each agent's task if it's not already present:
```
The commit SHA for this task is: <sha>
```
This prevents agents from getting stuck on placeholder text in their prompts.

---

## Zone B — Design patterns

Load this zone when designing a new workflow.

### System prompt design: two-step scripts

Agents with open-ended instructions produce variable call counts and unpredictable behavior. The most reliable pattern is two named steps with explicit scripts:

```
STEP 1 — Run this script exactly once (replace PLACEHOLDER with the value from your task):

import sys
sys.path.insert(0, '.')
from myworkflow.tools.my_tools import fetch_data
result = fetch_data('PLACEHOLDER')
print(result)

STEP 2 — Based only on the Step 1 output, write your response. Do not run any more code.
```

**Evidence from this codebase:**

| Agent | Before | After |
|---|---|---|
| `release_writer` | 1–16 LLM calls (avg 5.7), high variance | Exactly 5 calls, every run |
| `release_editor` | 3–18 LLM calls, worst case 194s | Exactly 3 calls, every run |
| `code_reader` | 3–6 calls, ~1,300 output tokens | Exactly 3 calls, ~252 tokens |

**Add an explicit stop condition** to prevent verification steps that fail due to working directory differences:
```
The output of Step 2 will begin with 'Written:' and include a 'File:' line showing where the entry was saved.
That output is your confirmation — the task is complete. Do not run cat, ls, or any other command to verify.
```

### Tool library pattern

Put shared logic in `tools/<workflow_name>_tools.py` as importable functions. Store persistent data in SQLite, not in ad-hoc files.

Agents import from this module in the scripts they run:
```python
import sys
sys.path.insert(0, '.')
from myworkflow.tools.my_tools import fetch_data, write_result
```

Scripts always run from `Orchestrator/` as cwd, so paths must be relative to that.

**Output directory pattern.** Functions should check an env var for the output path so a pipeline runner can set it per-repo without changing agent prompts:
```python
def _get_output_dir():
    env = os.environ.get('MY_OUTPUT_DIR')
    if env:
        return env
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
```

### Pipeline runner pattern

For workflows that loop over many inputs (commits, files, URLs):

1. Fetch the work queue
2. Filter to unprocessed items (check output files/DB — do not rely on in-memory state)
3. Call `orchestrator.py` as a subprocess for each item
4. Collect exit codes; report success/failure at the end

Recommended flags to always pass from the pipeline runner:
- `--loop` — caches plan template; saves ~8s per run after the first
- `--no-synthesis` — saves ~15s if the last agent already produces clean output
- `--stats-path <output_dir>/orchestrator_stats.jsonl` — per-repo log location
- Env var `MY_OUTPUT_DIR` — tells tool functions where to write

```python
def run_orchestrator(item_url, orchestrator_path, output_dir, verbose=False):
    task = f"Process this item: {item_url}"
    cmd = [
        "python3", str(orchestrator_path),
        "--task", task,
        "--stats-path", str(output_dir / "orchestrator_stats.jsonl"),
        "--loop", "--no-synthesis",
    ]
    if verbose:
        cmd.append("-v")
    env = os.environ.copy()
    env["MY_OUTPUT_DIR"] = str(output_dir)
    result = subprocess.run(cmd, cwd=str(TOP_DIR), env=env)
    return result.returncode == 0
```

Snapshot the stats file line count before the loop (`stats_start_line()`), then read entries from that point after the loop to compute cumulative stats without mixing in prior runs.

### Idempotency / "already processed" detection

Check disk artifacts to determine what's done. Don't rely on in-memory state across subprocess calls.

- Output files: check for a known marker (e.g., SHA7 hyperlink in a Markdown file)
- Database: add a `skip_reason` column; mark skipped items explicitly; union of written + skipped = fully processed
- The pipeline runner reads this set before each run and filters the queue

### Validation agent pattern

A validation/editor agent at the end of a pipeline can return:
- `APPROVED <one sentence>` → synthesizer reports success
- `NEEDS REVISION <specific issues>` → synthesizer reports the issues without aborting

To hard-block on failure: use `NEEDS_INPUT:` (marks step as failed in stats; synthesizer reports it).
To stop the whole pipeline early with a reason: use `SKIP_REMAINING:`.

### Security: external data agents

For agents that fetch content from untrusted sources (GitHub commit messages, web pages, user-provided URLs), set `"external_data": true` in the agent JSON. This tells the orchestrator to run the `--security medium` check against the raw tool output (what was actually fetched) rather than the agent's generated code. The agent's code is Python it wrote itself — not untrusted — and would produce constant false positives.

`--security medium` checks:
1. User task (before planning)
2. Tool output from `external_data` agents (after execution)

`--security high` is a strict superset of medium: also checks every step's task text and every agent's text response.

All security checks run regardless of mode through the regex prompt guard (no LLM calls, no overhead). `--security medium/high` adds LLM classification via a dedicated small model (Ministral 3B, ~0.25s per check).

---

## Zone C — Internal mechanics

Load this zone when debugging or extending the orchestrator itself.

### Plan cache internals (--loop mode)

After the first successful LLM planning call:
1. Orchestrator calls Ministral 3B to extract a `{variable}` template from the (task, plan) pair
2. Saves the template to `plan_cache.json` (alongside `orchestrator_stats.jsonl`)
3. On subsequent runs: Ministral extracts the variable value from the new task and substitutes into the template
4. Cache hit resolves in ~0.7s; a full LLM planning call takes ~8s
5. Cache is invalidated if the agent set changes (compared by agent name)
6. Any Ministral failure falls through to normal LLM planning

**Variable task strings** (e.g. one SHA or URL per run): task must have exactly one changing value. Ministral extracts it as `{variable}`. If there are multiple changing values, extraction fails and the cache never builds.

**Fixed task strings** (identical every run): also supported. Ministral stores the task with no `{variable}`. On subsequent runs, if the incoming task exactly matches the stored template, the cached plan is returned directly without calling Ministral at all. If the task doesn't match (different task type), it's treated as a cache miss and LLM planning runs normally.

**One cache per stats path.** `plan_cache.json` lives alongside `orchestrator_stats.jsonl`. A pipeline that routes different task types through the same orchestrator invocation shares one cache — the last task type's plan overwrites earlier ones. Each different task type will always miss and replan. This is fine when one task type dominates (researcher called N times), but wastes an LLM call at each phase transition. To avoid this, use a per-phase stats path so each task type gets its own cache file.

`plan_cache.json` structure:
```json
{
  "task_template": "Process this commit: {variable}",
  "plan_template": [
    {"agent": "code_reader", "task": "Fetch {variable} and save to database"},
    {"agent": "release_writer", "task": "Write a release note for {variable}"}
  ],
  "agents": ["code_reader", "release_editor", "release_writer"]
}
```

### OpenInterpreter configuration

Each agent and the orchestrator coordinator get a separate `OpenInterpreter` instance with no shared state. Message history is reset to `[]` before each task.

```python
itp = OpenInterpreter()
itp.llm.api_base = "http://127.0.0.1:1234/v1"
itp.llm.api_key = "x"
itp.llm.model = "openai/<detected-model-id>"   # must be prefixed with openai/
itp.llm.temperature = 0.2
itp.llm.context_window = 32000
itp.llm.max_tokens = 4000
itp.llm.supports_functions = True
itp.auto_run = True   # or False; from agent JSON
itp.system_message = "..."
```

Model IDs from LM Studio must be prefixed with `openai/`. Auto-detection queries `/v1/models` on startup and uses the first loaded model.

### Stats log format

Each run appends one JSON line to `orchestrator_stats.jsonl`:

```json
{
  "timestamp": "2026-05-26T...",
  "total_time_s": 48.8,
  "phases": [
    {
      "phase": "Planning (cached)",
      "tokens_in": 0, "tokens_out": 0, "llm_calls": 0, "time_s": 0.7
    },
    {
      "phase": "Step 1/3 · code_reader",
      "tokens_in": 312, "tokens_out": 756, "llm_calls": 3, "time_s": 16.0,
      "api_tokens_in": 2100, "api_tokens_out": 756
    }
  ],
  "totals": {
    "tokens_in": 1200, "tokens_out": 956, "llm_calls": 11, "out_tok_per_s": 19.8
  },
  "api_totals": {
    "tokens_in": 9800, "tokens_out": 956
  },
  "security_checks": {
    "level": "medium", "checks": 2, "threats_detected": 0,
    "total_time_s": 0.6, "tokens_in": 0, "tokens_out": 0, "llm_calls": 2
  }
}
```

**Two token-counting methods:**
- `tokens_in/out` in `phases[]` — message-body only. Simple, used for iteration comparison.
- `api_tokens_in/out` in `phases[]` and `api_totals` — system prompt × calls + cumulative context. Approximates what a cloud API would actually bill.

**Output mode by context:**
- In `--loop` mode: `print_summary_condensed()` prints two lines per run (timing + token counts, no cost table)
- In non-loop mode: `print_summary()` prints full table including illustrative cloud cost breakdown
- Pipeline runner: calls `print_pipeline_summary()` at end of loop using only entries written during this run (sliced by start line count)

### Reset

`release_pipeline.py --reset` deletes from the repo output directory:
- `release_data.db`
- `RELEASE_NOTES.md`
- `plan_cache.json`
- `orchestrator_stats.jsonl`

Does not touch agents, tools, or any source files.

### Failure modes reference

| Symptom | Likely cause | Fix |
|---|---|---|
| Agent reports failure after visibly succeeding | Agent ran a verification command from wrong working directory | Include full file path in tool return value; prohibit verification commands in prompt |
| Variable call counts, high worst-case run times | Open-ended system prompt | Redesign with explicit two-step scripts and a fixed call budget |
| Plan JSON parse failure, fallback to first agent | LLM added prose around the JSON | `extract_json()` uses regex and tolerates this; if it still fails, check that the planning model is actually loaded |
| Cache never builds | Task has multiple changing values per run | Ministral can only identify one `{variable}`; restructure the task to contain a single variable element |
| Planner creates a `__new__` intermediary agent before the intended one | Task string implies an unknown prerequisite (e.g. "the current product" → planner invents an identifier step) | Align the task string with the agent's description vocabulary. The description should reflect how the agent actually works (e.g. "reads queued file" not "for a specific named product") |
| Planner routes the wrong task type to a cached agent | Multiple task types share one `plan_cache.json`; last plan overwrites earlier ones | Use a per-phase stats path so each task type gets its own cache file |
| Security check always returns THREAT | Checking agent-generated code instead of fetched data | Set `"external_data": true` in the agent JSON to redirect the check to tool output |
| Agent silently skips remaining steps | Agent returned `SKIP_REMAINING:` | Intentional; check the agent's logic for the skip condition |
| Subprocess exits non-zero but agent appears to have worked | Output written to wrong directory | Check that `RELEASE_OUTPUT_DIR` (or equivalent env var) is set correctly in the pipeline runner |
