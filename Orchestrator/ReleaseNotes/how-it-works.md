# How the Multi-Agent Release Note System Works

## The Big Picture

This system automatically writes and verifies software release notes. You point it at a GitHub repository, it finds commits that don't have release notes yet, and it uses a local AI model to write a formatted entry for each one.

It's built on a general-purpose **orchestrator** pattern: a coordinator that breaks a task into steps and hands each step to a specialized AI agent. The release note pipeline is just one application of it. The orchestrator can be used for any multi-step task.

---

## The Three Pieces

### 1. `release_pipeline.py`: The Checker

This is the entry point for the release note workflow. You run it whenever you want to process new commits.

**What it does:**
1. Calls the GitHub API to get all commits for the target repository
2. Reads `RELEASE_NOTES.md` to see which commits are already documented (by looking for their short SHA as a link)
3. For each undocumented commit, invokes `orchestrator.py` as a subprocess and passes it the GitHub commit URL as the task
4. Processes commits oldest-first so the notes end up in chronological order

`release_pipeline.py` is the top of the call chain. The orchestrator has no knowledge of it. It just receives a task string and runs. You can also invoke the orchestrator directly for a single commit without going through the pipeline:
```bash
./orchestrator --task "Process this commit and write a release note: https://github.com/owner/repo/commit/abc1234"
```

**Key flags:**
- `--dry-run`: show what would be processed without actually running anything
- `--reset`: clear the database and delete `RELEASE_NOTES.md` to start fresh
- `--limit N`: process at most N new commits per run (useful when there's a big backlog)
- `--repo OWNER/NAME`: target a different GitHub repo (default: `geoff-codes-things/scripts`)
- `--token`: a GitHub personal access token, which raises the API rate limit from 60 to 5,000 requests/hour
- `--today`: process only commits from the last 24 hours. Uses a rolling window (not a calendar day), so a 2pm run always covers since 2pm yesterday. Does not read or write backlog state.
- `--backlog`: process one calendar day at a time, newest first. Saves its position so each run picks up where the last one left off. Auto-advances when a day is fully cleared. Useful for large repos where processing all history at once would exhaust the API rate limit.

**"Already captured" logic:** A commit is considered done if its 7-character SHA appears as a hyperlink in `RELEASE_NOTES.md`. If the pipeline partially failed (for example, the writer ran but the editor crashed), the commit will be retried on the next run.

---

### 2. `orchestrator.py`: The Coordinator

This is the general-purpose brain of the system. It takes any high-level task, figures out a plan, delegates the work to specialized agents, and combines their results into a final response.

It runs in **three phases**:

#### Phase 1: Plan

The orchestrator sends the task to the local LLM with a specific instruction: *"Don't do this yourself. Just output a list of which agents should handle which subtasks."*

For example, given the task `"Process this commit and write a release note"`, the LLM produces:

```json
{
  "plan": [
    {"agent": "code_reader", "task": "Fetch commit abc1234 from GitHub and save to the database"},
    {"agent": "release_writer", "task": "Write a release note for commit abc1234"},
    {"agent": "release_editor", "task": "Verify the release note for commit abc1234"}
  ]
}
```

The orchestrator parses this and uses it as its execution roadmap. If the LLM produces something it can't parse, it falls back to a single-step plan using the first available agent.

#### Phase 2: Execute

Each step in the plan is handed to its designated agent, one at a time. Agents run sequentially because later steps often depend on earlier ones (the writer needs the data that the code_reader saved, for example).

A few things happen automatically here:
- **SHA injection:** If the original task contains a commit SHA or a GitHub URL with one, the orchestrator extracts it and appends it to each agent's task description. This prevents agents from getting confused by placeholder text in their instructions.
- **Failure detection:** After each agent finishes, the orchestrator checks whether the response looks like a question or an error (phrases like "I need the SHA," "please provide," or a response that ends with a question mark). If so, it flags that step as failed and marks it clearly so the synthesizer knows.

#### Phase 3: Synthesize

After all agents finish, the orchestrator passes all their results to the LLM one more time and asks it to write a clean summary for the user. If a step failed, the synthesizer reports that rather than pretending everything worked.

#### On-the-fly agents

If the LLM decides none of the available agents fit a step, it can invent a new one on the spot, specifying a name, description, and system prompt. After the run, the orchestrator asks if you want to save the new agent to disk for future use.

---

### 3. `agents/`: The Specialists

Each agent is a JSON file in the `agents/` directory. The orchestrator loads all of them at startup. An agent definition has five fields:

```json
{
  "name": "agent_name",
  "description": "One sentence used by the planner to decide when to use this agent",
  "system_prompt": "Full instructions for the LLM when acting as this agent",
  "auto_run": true,
  "external_data": true
}
```

- **`name`**: used to reference the agent in plans
- **`description`**: the planner reads this to decide which agent fits which job
- **`system_prompt`**: the most important field. This is the complete set of instructions the LLM follows when acting as this agent. It should be specific about what to do and how.
- **`auto_run`**: whether the agent can run code automatically. `true` for agents that need to execute Python (like `code_reader`). `false` for agents that only produce text (like a `writer`).
- **`external_data`**: marks agents that fetch content from outside the system (GitHub API, web pages, etc.). At `--security medium` or `high`, the LLM security check runs against the raw data these agents fetch rather than their generated code, targeting the actual untrusted content.

**The three release note agents:**

| Agent | What it does | `auto_run` |
|---|---|---|
| `code_reader` | Fetches a commit from the GitHub API and saves it to `release_data.db` | true |
| `release_writer` | Reads the saved commit data and writes a formatted entry into `RELEASE_NOTES.md` | true |
| `release_editor` | Re-reads the commit data and the written note, then returns APPROVED or NEEDS REVISION | true |

Each agent is a separate AI instance with its own instructions and message history. Agents don't share memory. The only shared state between them is the files they read and write: the database and `RELEASE_NOTES.md`.

---

## The Shared Tools (`tools/`)

Rather than having agents write complex Python from scratch each time, shared logic lives in `tools/release_tools.py` as importable functions. Agents import from it directly in the code they write:

```python
from tools.release_tools import fetch_commit_data, write_release_entry
```

- **`fetch_commit_data(sha)`**: looks up a commit in `release_data.db` and returns its metadata and file diffs
- **`write_release_entry(sha, summary, change_type)`**: handles all the formatting and inserts the entry into `RELEASE_NOTES.md` in the right place

This keeps agent prompts shorter and makes behavior consistent across runs.

---

## Security

The orchestrator runs two layers of injection detection before any agent acts on text.

### Layer 1: Regex prompt guard (always active)

`check_prompt()` in `orchestrator.py` matches text against a set of known attack patterns grouped into four categories:

| Category | Examples caught |
|---|---|
| Direct Override | "ignore all your instructions", "disregard former guidance" |
| Code Execution Exploit | `os.system(`, `rm -rf`, `curl … \| bash`, `/etc/passwd` |
| Memory Reconstruction | "reveal your system prompt", "repeat everything above" |
| Authority Impersonation | "I am your developer", "from now on you are", "developer mode" |

Three checkpoints run on every execution:

1. **User task**: checked before planning begins. A hit returns an error immediately and no agents run.
2. **Each step's task**: checked before the agent is invoked. A hit stops the pipeline immediately with no further steps and no synthesis.
3. **Each agent's response**: checked before the result is passed to the next step. A hit replaces the response with a `[RESPONSE QUARANTINED]` message but does not stop the pipeline. The run continues with the sanitized result. The AI security check (Layer 2) aborts the pipeline entirely on a hit, rather than continuing.

The regex guard is fast (no LLM calls) but limited to known patterns. Novel or paraphrased attacks can slip through.

### Layer 2: LLM security check (`--security medium` or `--security high`)

The `--security` flag enables a second pass after the regex guard, using a small dedicated LLM to classify text as `SAFE` or `THREAT`. Its purpose is to catch attacks that pattern matching misses: paraphrased overrides, indirect authority claims, and other semantic variations.

The check runs as `tools/security_check.py`, a standalone subprocess. It takes text on stdin, prints one word (`SAFE` or `THREAT`) to stdout, and exits. Keeping it separate makes it independently testable without running the full pipeline.

**Two levels:**

| Flag | What gets checked |
|---|---|
| `--security medium` | User task input + tool output from agents that pull external data (`code_reader`) |
| `--security high` | Everything in medium, plus every step task and every agent response |

Medium covers the points where untrusted content actually enters the pipeline. High is a strict superset — it adds checks at every remaining point in the pipeline.

For `external_data` agents like `code_reader`, the check targets the raw data that was fetched: the commit message, diff, and filenames. The agent's generated Python code is not checked. That code would trigger constant false positives. If a THREAT is detected, the pipeline aborts immediately and no downstream agents run.

**Dedicated security model.** The LLM check uses a separate, smaller model rather than the main pipeline model. After testing several options, `mistralai/ministral-3-3b` was chosen. It runs the check in 0.1-0.6 seconds and outputs a bare word with no preamble. The main pipeline model (Qwen 3.5-35b) took 8-13 seconds per check for the same task. Override with `--security-model MODEL`.

**Fail-closed:** Any outcome other than a clear `SAFE` (timeout, API error, or unrecognizable response) is treated as a threat.

**Stats isolation:** Security check time and token counts are tracked separately in `orchestrator_stats.jsonl` and never mixed into pipeline phase timings.

---

## Data Flow

```
release_pipeline.py  <-- you run this
    |  (loops over commits, calls orchestrator as a subprocess for each one)
    v
orchestrator.py
    |  (plans, then runs agents in sequence)
    +-- code_reader --fetches-- GitHub API --saves--> release_data.db
    |                                                        |
    +-- release_writer <--reads-------------------------------+
    |       +-writes-> RELEASE_NOTES.md
    |                          |
    +-- release_editor <--reads both--> APPROVED / NEEDS REVISION
```

The only communication between agents is through files on disk. There is no message passing or shared memory.

---

## Using the Orchestrator for Other Scenarios

The orchestrator is not tied to release notes at all. You can use it for any task that can be broken into subtasks with different specializations. Some examples:

- **Research + write:** a `researcher` agent finds information, a `writer` agent drafts the document
- **Code + review:** a `coder` agent writes a function, a `reviewer` agent checks it
- **Scrape + analyze + summarize:** three agents working in sequence on data collection, analysis, and reporting

To add a new agent, create a JSON file in `agents/`. The orchestrator picks it up automatically on the next run. No code changes needed.

The description field is what the planner uses to route tasks. Write it precisely. "Fetches weather data from the NOAA API and returns current conditions as JSON" is more useful than "gets weather."

---

## Statistics and Logging

After every run, the orchestrator prints a table showing:
- Tokens sent to the model (input) and generated (output), per phase
- Number of LLM calls made
- Time spent in each phase
- **Output throughput** (tok/s): output tokens per second, used as an energy proxy
- Illustrative cost estimates if you were running on a paid API

It also appends a JSON record to `orchestrator_stats.jsonl` so you can review usage over time. Each record includes `out_tok_per_s` in its `totals` block.

**Why throughput approximates energy:** inference power draw on a given machine is roughly constant while the model is generating. That means energy consumed ≈ wall time × constant. Reducing time by 30% reduces energy by roughly 30%. Output tok/s captures this: a higher number means the same generation work completed in less time, at less energy cost. It doesn't require any additional instrumentation.

---

## Dependencies

### Required

| Dependency | What it's for | Install |
|---|---|---|
| **Open Interpreter** | The framework that runs agents. Handles LLM calls, code execution, and message formatting. | `pip install open-interpreter` |
| **LM Studio** | Runs the local LLM and serves it via an OpenAI-compatible API at `http://127.0.0.1:1234/v1` | [lmstudio.ai](https://lmstudio.ai) |
| **Python 3.9+** | Runtime for all scripts | (already installed) |
| **SQLite** | Built into Python's standard library. Used for `release_data.db`. | (no install needed) |

### Optional

| Dependency | What it's for | Install |
|---|---|---|
| **tiktoken** | Accurate token counting in the stats table. Falls back to a rough estimate if not installed. | `pip install tiktoken` |

### External services

| Service | Used for | Auth required? |
|---|---|---|
| **GitHub REST API** | Fetching commit lists and commit data | No (public repos). A personal access token raises the rate limit from 60 to 5,000 req/hour. |

---

## Initial Results and Iterations

### Baseline

After building the system, we ran the full pipeline against all 21 commits in the `geoff-codes-things/scripts` repository. The first 17 runs (logged to `orchestrator_stats-pre_adjust.jsonl`) established the baseline. Each one processed a single commit through the three-agent pipeline (code_reader, release_writer, release_editor) plus planning and synthesis.

**Overall throughput:** ~122 seconds per commit on average (range: 93-191s).

| Phase | Avg time | Avg LLM calls | Notes |
|---|---|---|---|
| Planning | ~7.5s | 1 (always) | Very consistent |
| code_reader | ~40s | 3-6 | Biggest time sink (33% of total) |
| release_writer | ~29s | 1-16 (avg 5.7) | Most variable agent |
| release_editor | ~25s | 3-9 | Moderate variance |
| Synthesis | ~19s | 1 (always) | Very consistent |

**code_reader dominated** because the agent wrote HTTP request code and SQLite schema from scratch on every run, generating ~1,300 output tokens per call. On some runs it needed as many as 6 LLM calls, pushing total time well above average.

**release_writer was the most unpredictable agent.** Call counts swung from 1 to 16 (avg 5.7). The worst run spent 77.6 seconds and 1,743 tokens in the writer alone. The root cause: the original prompt asked the model to print data and fill in values in the same script, which doesn't work. The model would loop trying to re-run the script with corrections.

**Output tokens ran ~3.4x input tokens.** This is inverted from typical LLM usage. Agents generate code, run it, read results, and sometimes retry. On a paid API, output costs would dominate.

---

### Iteration 1: `store_commit_data()` tool + two-step writer prompt

**What changed:**

1. **code_reader refactored to call a shared tool.** A `store_commit_data(url)` function was added to `tools/release_tools.py` that handles the full GitHub API fetch and SQLite save. The code_reader system prompt was reduced to a 5-line script that calls this one function. The agent no longer writes HTTP or database code from scratch.

2. **release_writer prompt redesigned as two explicit steps.** The new prompt separates fetch (Step 1, run once) and write (Step 2, run once) into two named scripts. The model is told exactly which script to run in each step. This eliminated the ambiguity that caused the retry loop.

**Results** (19 valid runs from `orchestrator_stats.jsonl`; one run excluded as an anomaly where the synthesis phase hung for ~16 hours):

| Metric | Baseline | Iteration 1 | Change |
|---|---|---|---|
| Avg total time | 121.6s | 94.3s | **-22%** |
| Time range | 93-191s | 62-194s | Floor dropped 30s |
| code_reader time | ~40s | ~12.6s | **-69%** |
| code_reader output tokens | ~1,328 | ~252 | **-81%** |
| Writer call count | 1-16 (avg 5.7) | 5 (every single run) | **Fully deterministic** |
| Writer time | ~29s | ~17s | **-41%** |
| Total output tokens | ~2,977 | ~2,130 | **-29%** |

The most striking result is the writer: every one of the 19 new runs used exactly 5 LLM calls. The two-step design didn't just reduce retries, it made the agent's behavior perfectly consistent. The code_reader improvement is similarly clean: 3 calls every run, ~12 seconds, down from a 38-72 second range.

**The new bottleneck:** With code_reader and writer stabilized, the editor became the primary source of variance. Editor call counts ranged from 3 to 18, and the three worst total run times (134s, 144s, 194s) were driven entirely by editor retries. This was the next target for a prompt tightening pass.

---

### Iteration 2: editor redesign + security check

**What changed:**

1. **release_editor redesigned with the same two-step pattern as the writer.** The previous editor prompt gave the agent open-ended instructions, which led to highly variable call counts. The new prompt gives the agent two named scripts: run the first one to fetch data, then issue a verdict based only on that output. No further code allowed. A new `fetch_editor_data(sha)` function in `release_tools.py` fetches commit metadata and the written release note entry in a single call, so the agent gets everything it needs in one shot.

2. **`--extra-secure` mode added.** Running the pipeline with this flag enables the LLM-based security checks described in the Security section above. All 21 runs in this iteration used `--extra-secure`.

**Results** (15 full three-agent runs; 6 commits were flagged by code_reader as not needing release notes and took a shorter path):

| Metric | Iteration 1 | Iteration 2 (pipeline only) | Change |
|---|---|---|---|
| Avg total time | 94.3s | 69.2s | **-27%** |
| Time range | 62-194s | 63-78s | Ceiling collapsed |
| release_editor calls | 3-18 (variable) | 3 (every single run) | **Fully deterministic** |
| release_editor time | variable | ~13s avg | Consistent |
| release_writer calls | 5 (every run) | 5 (every run) | Unchanged |
| code_reader calls | 3 (every run) | 3 (every run) | Unchanged |
| Avg output tokens | ~2,130 | ~1,480 | **-31%** |

The editor result mirrors what happened to the writer in Iteration 1: the same two-step fix turned a highly variable agent into a predictable one. Every run used exactly 3 LLM calls. The worst-case total time dropped from 194s to 78s, which was the main goal.

**Security overhead with `--extra-secure`:**

The security checker runs 7 times per full pipeline run (once for the user task, once before each agent, once after each agent). Each check is an independent LLM call that takes around 10-11 seconds.

| | Pipeline only | With `--extra-secure` |
|---|---|---|
| Avg time (full run) | 69.2s | 142.6s |
| Time range (full run) | 63-78s | 133-151s |
| Avg time (SKIP run) | 36.1s | 65.4s |
| Extra LLM calls | 0 | 7 (full) or 3 (SKIP) |

The security layer adds about 73 seconds to a full run, roughly doubling wall time. That is the tradeoff for `--extra-secure`: comprehensive coverage at significant cost. No threats were detected in any of the 21 runs, which is expected for a normal commit history. The flag is optional. Without it, the regex guard (Layer 1) still runs on every execution at no extra cost.

---

### Iteration 3: tiered security and dedicated security model

**What changed:**

1. **`--extra-secure` replaced with `--security low/medium/high`.** The old flag ran LLM checks at all seven checkpoints every time. The new flag gives three options. `low` (default) runs the regex guard only. `medium` adds LLM checks at the two points where untrusted content enters: the user task and the commit data fetched by `code_reader` (checked against the tool console output, not the agent's generated code). `high` restores the full seven-checkpoint behavior.

2. **Security checks moved to a dedicated small model.** The original implementation reused the main pipeline model (Qwen 3.5-35b-a3b) for security classification. This worked but was slow. Binary classification does not require a large reasoning model, so three models were benchmarked on a five-case test set (three SAFE inputs, two clear THREAT inputs):

| Model | Accuracy | Avg time per check | Notes |
|---|---|---|---|
| Qwen 3.5-35b-a3b | 5/5 | 8-13s | Correct but slow. Reasoning preamble stripped by classifier. |
| phi-4-mini-reasoning | 4/5 | 0.4-19s | False positive on a plain pipeline URL. Unreliable output format. |
| Ministral 3B | 5/5 | 0.1-0.6s | Direct single-word output. No preamble to strip. |

Ministral 3B was chosen. It is accurate, consistent, and 20-50x faster than Qwen on this task. It loads alongside the pipeline model without meaningful VRAM pressure.

**Results** (7 runs against `geoff-codes-things/scripts` with `--security medium`; 6 full three-agent runs, 1 SKIP):

| Metric | Iteration 2 (pipeline only) | Iteration 3 (`--security medium`) | Change |
|---|---|---|---|
| Avg total time | 69.2s | 71.0s | +1.8s |
| Time range | 63-78s | 62.5-78.9s | Essentially unchanged |
| Security overhead | 73.4s (--extra-secure) | 0.8s avg (0.5-1.0s) | **-99%** |
| Security LLM calls | 7 per full run | 2 per run | **-71%** |
| Threats detected | 0 | 0 | — |
| code_reader calls | 3 (every run) | 3 (every run) | Unchanged |
| release_writer calls | 5 (every run) | 5 (every run) | Unchanged |
| release_editor calls | 3 (every run) | 3 (every run) | Unchanged |

The pipeline timing is unchanged. Adding `--security medium` costs under one second. The security overhead that nearly doubled run time under `--extra-secure` is now a rounding error. Agent call counts remain fully deterministic across all runs.

---

### Iteration 4: plan caching and synthesis removal

**What changed:**

1. **`--no-synthesis` flag added.** The synthesis phase passed the editor's already-verified output to the main LLM and asked it to produce a summary. For the release note pipeline the editor already returns a clean, formatted entry, so synthesis was generating output nobody needed. Removing it saves ~15 seconds per run.

2. **`--loop` flag with plan caching added.** Every commit was triggering an ~8-second planning LLM call (main model) to produce the same three-step plan. With `--loop`, the orchestrator caches the plan after the first run. Ministral 3B extracts a `{variable}` template from the task and plan, identifying the commit URL as the part that changes between runs. On subsequent runs, Ministral extracts the URL from the new task and substitutes it in, resolving the plan in ~0.7 seconds. The main model is not involved. The cache (`plan_cache.json`) is invalidated automatically if the agent set changes.

**Results** (16 full three-agent runs; 4 commits were flagged by code_reader as not needing release notes):

| Metric | Iteration 3 | Iteration 4 | Change |
|---|---|---|---|
| Avg total time | 71.0s | 48.8s | **-31%** |
| Time range | 62.5-78.9s | 41-83s | — |
| Planning | ~8s (LLM) | 0.7s (Ministral cache) | **-91%** |
| code_reader time | ~15s avg | 16.0s avg | ~same |
| release_writer time | ~18s avg | 15.9s avg | ~same |
| release_editor time | ~13s avg | 15.6s avg | ~same |
| Synthesis | ~15s | eliminated | — |
| Security overhead | 0.8s avg | 0.6s avg | ~same |
| Avg output tokens | ~1,475 | ~956 | **-35%** |
| Avg tok/s | ~21.2 | 19.8 | ~same |

Agent phase timings are similar to prior iterations, within normal run-to-run variance. The gains come entirely from two eliminated LLM calls: the planning call (replaced by Ministral template resolution) and the synthesis call (removed). Together they account for the full ~22-second improvement.

The output token drop (-35%) reflects synthesis removal: the main model no longer generates a wrap-up response. The tok/s throughput is unchanged, confirming the model runs at the same speed. The pipeline is just doing less work.

---

### Energy perspective across iterations

**Measured power draw (MacBook Pro M4 Pro, Mac16,8):**

Power was sampled at 2-second intervals using `powermetrics` during an idle baseline and a live pipeline run. The incremental draw attributable to inference (active minus idle):

| Subsystem | Idle | Active (inferring) | Incremental |
|---|---|---|---|
| GPU (Metal) | ~16 mW | ~15,570 mW | ~15,554 mW |
| CPU | ~73 mW | ~996 mW | ~923 mW |
| ANE | 0 mW | 0 mW | 0 mW |
| **Total** | **~89 mW** | **~16,566 mW** | **~16.5 W** |

The GPU accounts for 94% of the inference draw. LM Studio uses Metal for inference. The Apple Neural Engine (ANE) is not involved. Idle system power is negligible (89 mW).

With 16.5 W incremental draw, energy per run = **16.5 W × total wall time** (pipeline + security):

| | Baseline | Iteration 1 | Iteration 2 | Iteration 3 | Iteration 4 |
|---|---|---|---|---|---|
| Pipeline time | 121.6s | 94.3s | 69.2s | 71.0s | 48.2s |
| Security overhead | — | — | 73.4s | 0.5s | 0.6s |
| **Total time** | **121.6s** | **94.3s** | **142.6s** | **71.5s** | **48.8s** |
| Avg output tokens | ~2,977 | ~2,130 | ~1,480 | ~1,475 | ~956 |
| Output tok/s (pipeline) | ~24.2 | ~22.5 | ~21.4 | ~21.2 | ~19.8 |
| **Energy per run** | **2,004 J (0.557 Wh)** | **1,554 J (0.432 Wh)** | **2,350 J (0.653 Wh)** | **1,178 J (0.327 Wh)** | **805 J (0.224 Wh)** |
| **Microwave-seconds** | **2.0** | **1.6** | **2.4** | **1.2** | **0.8** |
| vs baseline | — | **-22%** | **+17%** | **-41%** | **-60%** |

*Microwave-seconds: equivalent energy to running a 1,000 W microwave for that many seconds.*

The constant pipeline throughput (tok/s) confirms that efficiency gains came entirely from reducing work (fewer retries, tighter prompts, shared tools), not from making the model run faster.

Iteration 2 is the instructive case: the pipeline itself improved by 27%, but adding `--extra-secure` used the same large main model for security classification, adding 73 seconds per run. That erased all gains and pushed total energy **above** baseline. Iteration 3 recovered them by switching to a dedicated 3B security model that completes each check in ~0.25 seconds. The security overhead went from 73.4s to 0.5s, making it a rounding error. Iteration 4 then eliminated two redundant LLM calls (planning replaced by cached template resolution, synthesis removed entirely), cutting another 22 seconds and bringing total energy to 60% below baseline.

**At scale: 100-commit backlog**

| | Baseline | Iter 1 | Iter 2 | Iter 3 | Iter 4 |
|---|---|---|---|---|---|
| Total energy | 200 kJ | 155 kJ | 235 kJ | 118 kJ | 81 kJ |
| Watt-hours | 55.7 Wh | 43.2 Wh | 65.3 Wh | 32.7 Wh | 22.4 Wh |
| Microwave-seconds | 200 | 155 | 235 | 118 | 81 |
| vs baseline | — | -22% | **+17%** | **-41%** | **-60%** |

---

## Real-World Cost Estimate

The relevant unit for a business is the whole engineering organisation, not a single repo. The question is: how many **release-note-worthy commits** does the company produce per day across all its repos?

Not every commit qualifies. Automated PRs (Dependabot, Renovate, version bumps, bot-generated changelogs) typically make up 50-70% of an active org's total commit volume. Release notes are about what engineers shipped, so the relevant count is **human PR merges to main and release branches**. PostHog is a ~100-engineer open-source company with 84 active public repos. It produced ~1,139 commits/day across all branches as of May 2026. Roughly a third of those reach main, and about half of those are human-authored. That works out to ~100-200 meaningful commits per day for a company that size.

| Company tier | Engineering org | Active repos | Release-note commits/day | Run time/day | Energy/day | Elec. cost/yr |
|---|---|---|---|---|---|---|
| **Small** | 5–25 engineers | 4–15 | ~15 | 12 min | 3.4 Wh | $0.18 |
| **Medium** | 25–150 engineers | 15–50 | ~100 | 1.4 hr | 22.4 Wh | $1.22 |
| **Large** | 150–1,000 engineers | 50–300 | ~600 | 8.1 hr | 134 Wh | $7.35 |
| **Enterprise** | 1,000+ engineers | 300–1,000+ | ~2,500 | 33.9 hr | 559 Wh | $30.61 |

Electricity at $0.15/kWh (US commercial average). Processing rate: 48.8 s/commit (Iteration 4, `--security medium`, MacBook Pro M4 Pro, measured).

**Infrastructure assessment:**

A single machine processes ~590 commits in an 8-hour nightly window, or ~1,770 commits running continuously.

| Tier | Infrastructure needed |
|---|---|
| Small | 1 machine. Runs in ~12 minutes. Can share with other dev work. |
| Medium | 1 machine. ~80-minute nightly batch. Fits comfortably in a nightly window. |
| Large | 1 machine, needs to run most of the day (~8 hours). Dedicated machine justified. |
| Enterprise | 2 machines running in parallel. Each handles ~1,250 commits/day, covering 2,500 total. |

The crossover from nightly batch to continuous processing happens around 590 commits/day — where the full 8-hour nightly window is exhausted. That is roughly where a 250-engineer team lands. Below that, a nightly batch is enough. Above it, switching to continuous processing extends capacity to ~1,770 commits/day before a second machine is needed.

**Electricity cost is not a factor at any tier.** Even an enterprise running 2 dedicated machines costs ~$61/year in electricity ($30.61 × 2). Hardware is the real line item: two Mac mini M4 Pros run ~$933/year amortized over three years. A more meaningful comparison is the cost of writing release notes manually. At enterprise scale, that can easily consume a full-time engineer's time.

---

## File Layout

```
Orchestrator/
├── orchestrator.py          # The general-purpose orchestrator
├── orchestrator             # Shell wrapper (run as ./orchestrator --task "...")
├── agents/
│   ├── code_reader.json
│   ├── release_writer.json
│   ├── release_editor.json
│   └── writer.json          # General-purpose prose writer (sample agent)
├── tools/
│   └── security_check.py    # Standalone LLM security classifier
└── ReleaseNotes/
    ├── release_pipeline.py  # Commit checker and pipeline runner
    ├── release_pipeline     # Shell wrapper (run as ./release_pipeline)
    ├── tools/
    │   ├── release_tools.py       # Shared logic: fetch_commit_data, write_release_entry
    │   ├── fetch_commit_data.py   # CLI: look up a commit in the local database
    │   └── write_release_entry.py # CLI: manually write a release note entry
    └── output/              # Gitignored. Created at runtime, one directory per repo.
        └── owner_repo/
            ├── release_data.db          # SQLite database of fetched commits
            ├── RELEASE_NOTES.md         # Generated release notes
            ├── orchestrator_stats.jsonl # Token and timing log
            └── plan_cache.json          # Cached plan template (--loop mode)
```
