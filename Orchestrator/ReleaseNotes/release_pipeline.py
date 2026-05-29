#!/usr/bin/env python3
# release_pipeline.py
#
# This script is intended to:
#    - Fetch commits from a GitHub repo via the API
#    - Compare against commits already documented in RELEASE_NOTES.md
#    - Run the orchestrator workflow for any new commits (oldest first)
#
# Written by Geoff Kottmeier, 2025

import argparse
import sys
import os
import re
import json
import subprocess
import urllib.request
import traceback
from datetime import datetime, timedelta, date as date_type
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent           # Orchestrator/ReleaseNotes/
TOP_DIR    = SCRIPT_DIR.parent               # Orchestrator/
OUTPUT_DIR = SCRIPT_DIR / "output"

sys.path.insert(0, str(SCRIPT_DIR))

GITHUB_API = "https://api.github.com"

# ============= ARGUMENTS =============

parser = argparse.ArgumentParser(
    description="Finds new commits in a GitHub repo and runs the release note pipeline for each.",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""Examples:
  python release_pipeline.py
  python release_pipeline.py --repo geoff-codes-things/scripts --limit 5
  python release_pipeline.py --today
  python release_pipeline.py --backlog --limit 10
  python release_pipeline.py --security medium
  python release_pipeline.py --dry-run
  python release_pipeline.py --reset
  python release_pipeline.py --token ghp_abc123
"""
)
parser.add_argument("--repo", default="geoff-codes-things/scripts",
                    help="GitHub repo in owner/name format. (default: geoff-codes-things/scripts)",
                    metavar="OWNER/REPO")
parser.add_argument("--branch", default=None,
                    help="Branch to process. Auto-detects the repo's default branch if not specified.",
                    metavar="BRANCH")
parser.add_argument("--limit", type=int, default=None,
                    help="Maximum number of new commits to process per run.",
                    metavar="N")
parser.add_argument("--dry-run", action="store_true",
                    help="Show which commits would be processed without running the pipeline.")
parser.add_argument("--reset", action="store_true",
                    help="Clear release_data.db and RELEASE_NOTES.md for the target repo before processing.")
parser.add_argument("--token", default=None,
                    help="GitHub personal access token (increases API rate limit).",
                    metavar="TOKEN")
parser.add_argument("--orchestrator", default=str(TOP_DIR / "orchestrator.py"),
                    help="Path to orchestrator.py. (default: ../orchestrator.py)",
                    metavar="PATH")
parser.add_argument("--security", choices=["low", "medium", "high"], default="low",
                    help="Security level passed to the orchestrator. (default: low)",
                    metavar="LEVEL")
mode_group = parser.add_mutually_exclusive_group()
mode_group.add_argument("--today", action="store_true",
                        help="Process only today's commits. Does not read or write backlog state.")
mode_group.add_argument("--backlog", action="store_true",
                        help="Process one day at a time, newest first. Advances automatically when a day is fully cleared.")
parser.add_argument("-v", "--verbose", action="store_true",
                    help="Enable verbose output with timestamps.")

# ============= CONSOLE OUTPUT =============

def verbosePrintSetup(verbosestate):
    if verbosestate:
        def verboseprintfunc(*args):
            timestampstr = datetime.now().strftime("%Y-%m-%d, %H:%M:%S")
            print(timestampstr + ' - verbose: ', end='')
            for arg in args:
                print(str(arg), end=' ')
            print()
    else:
        verboseprintfunc = lambda *a: None
    return verboseprintfunc

verboseprint = lambda *a: None

# ============= UTILITIES =============

# Returns the repo's default branch name from the GitHub API.
def fetch_default_branch(repo, token=None):
    url = f"{GITHUB_API}/repos/{repo}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "release-pipeline"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as resp:
            return json.loads(resp.read()).get('default_branch', 'main')
    except Exception as e:
        verboseprint(f"Could not detect default branch: {e} — falling back to 'main'")
        return 'main'

# Fetches commits from a GitHub repo, paginating until exhausted or max_commits is reached.
# max_commits caps the fetch so --limit runs on large repos don't burn the rate limit.
def fetch_github_commits(repo, token=None, max_commits=None, since=None, until=None, branch=None):
    commits = []
    page = 1
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "release-pipeline"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    while True:
        url = f"{GITHUB_API}/repos/{repo}/commits?per_page=100&page={page}"
        if branch:
            url += f"&sha={branch}"
        if since:
            url += f"&since={since}"
        if until:
            url += f"&until={until}"
        verboseprint(f"Fetching page {page}: {url}")
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            raise RuntimeError(f"GitHub API error {e.code} for {url}: {body}")
        if not data:
            break
        commits.extend(data)
        verboseprint(f"  Got {len(data)} commits (total so far: {len(commits)})")
        if len(data) < 100:
            break
        if max_commits and len(commits) >= max_commits:
            verboseprint(f"  Fetch cap reached ({max_commits} commits) — stopping pagination.")
            break
        page += 1
    return commits

# Returns the set of sha7s already present as links in RELEASE_NOTES.md.
def get_noted_sha7s(notes_path):
    if not notes_path.exists():
        return set()
    content = notes_path.read_text(encoding='utf-8')
    return set(re.findall(r'\[([0-9a-f]{7})\]\(https://github\.com/[^)]+\)', content))

# Returns the set of sha7s marked as skip in the database.
def get_skipped_sha7s(output_dir):
    try:
        os.environ['RELEASE_OUTPUT_DIR'] = str(output_dir)
        from tools.release_tools import get_skipped_sha7s as _get
        return set(_get().keys())
    except Exception:
        return set()

BACKLOG_STATE_FILE = "backlog_state.json"

# Loads the current backlog date from state file. Returns today if no state exists.
def load_backlog_date(output_dir):
    path = output_dir / BACKLOG_STATE_FILE
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return datetime.strptime(data['date'], '%Y-%m-%d').date()
        except Exception:
            pass
    return datetime.now().date()

# Saves the current backlog date to state file.
def save_backlog_date(output_dir, d):
    path = output_dir / BACKLOG_STATE_FILE
    path.write_text(json.dumps({'date': d.strftime('%Y-%m-%d')}))

# Removes all generated files for a repo's output directory.
def reset_data(output_dir):
    targets = [
        output_dir / "release_data.db",
        output_dir / "RELEASE_NOTES.md",
        output_dir / "plan_cache.json",
        output_dir / "orchestrator_stats.jsonl",
    ]
    any_found = False
    for path in targets:
        if path.exists():
            path.unlink()
            print(f"  Deleted: {path}")
            any_found = True
    if not any_found:
        print("  Nothing to delete — output directory is already clean.")

# Returns the current line count of the stats file (used to slice only this run's entries later).
def stats_start_line(stats_path):
    try:
        with open(stats_path, 'r', encoding='utf-8') as f:
            return sum(1 for _ in f)
    except FileNotFoundError:
        return 0

_CLOUD_MODELS = [
    ("Gemini 2.0 Flash",  0.10,  0.40),
    ("GPT-4o mini",       0.15,  0.60),
    ("Claude Haiku 3.5",  0.80,  4.00),
    ("GPT-4o",            2.50, 10.00),
    ("Claude Sonnet 4.5", 3.00, 15.00),
]

# Reads stats entries written since start_line and prints a cumulative summary with costs.
def print_pipeline_summary(stats_path, start_line, succeeded, failed):
    try:
        with open(stats_path, 'r', encoding='utf-8') as f:
            entries = [json.loads(l) for l in f.readlines()[start_line:] if l.strip()]
    except Exception:
        return
    if not entries:
        return

    total_time  = sum(e['total_time_s']              for e in entries)
    total_calls = sum(e['totals']['llm_calls']        for e in entries)
    total_out   = sum(e['totals']['tokens_out']       for e in entries)
    api_in      = sum(e.get('api_totals', {}).get('tokens_in',  0) for e in entries)
    api_out     = sum(e.get('api_totals', {}).get('tokens_out', 0) for e in entries)
    tok_s       = total_out / max(total_time, 0.001)

    W = 60
    print("═" * W)
    print("  Run Summary")
    print("═" * W)
    print(f"  {'Commits processed':<28} {len(entries):>8}")
    print(f"  {'Succeeded':<28} {succeeded:>8}")
    if failed:
        print(f"  {'Failed':<28} {len(failed):>8}  ({', '.join(failed)})")
    print(f"  {'Total wall time':<28} {total_time:>7.1f}s")
    print(f"  {'Avg per commit':<28} {total_time/max(len(entries),1):>7.1f}s")
    print(f"  {'Total LLM calls':<28} {total_calls:>8,}")
    print(f"  {'Output tok/s (energy proxy)':<28} {tok_s:>7.1f}")
    if api_in or api_out:
        print()
        print(f"  {'─'*58}")
        print(f"  Estimated cost if run on cloud API ({api_in:,} in / {api_out:,} out tokens)")
        print(f"  {'─'*58}")
        for name, r_in, r_out in _CLOUD_MODELS:
            c = (api_in / 1_000_000 * r_in) + (api_out / 1_000_000 * r_out)
            print(f"  {name:<26} ${c:.4f}  (${c/max(len(entries),1):.5f}/commit)")
    print("═" * W + "\n")

# Runs the orchestrator pipeline for one commit URL. Returns True on success.
def run_orchestrator(commit_url, orchestrator_path, output_dir, verbose=False, security="low", branch=None):
    task = (
        f"Process this GitHub commit, write a release note, and verify it: {commit_url}"
    )
    stats_path = output_dir / "orchestrator_stats.jsonl"
    cmd = [sys.executable, str(orchestrator_path), "--task", task, "--stats-path", str(stats_path),
           "--loop", "--no-synthesis"]
    if verbose:
        cmd.append("-v")
    if security != "low":
        cmd.extend(["--security", security])

    env = os.environ.copy()
    env["RELEASE_OUTPUT_DIR"] = str(output_dir)
    if branch:
        env["RELEASE_BRANCH"] = branch

    verboseprint(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(TOP_DIR), env=env)
    verboseprint(f"Orchestrator exit code: {result.returncode}")
    return result.returncode == 0

# ============= EXECUTION =============

def run():
    args = parser.parse_args()

    global verboseprint
    verboseprint = verbosePrintSetup(args.verbose)

    repo_slug  = args.repo.replace('/', '_')
    output_dir = OUTPUT_DIR / repo_slug
    db_path    = output_dir / "release_data.db"
    notes_path = output_dir / "RELEASE_NOTES.md"

    if args.reset:
        print(f"Resetting data for {args.repo}...")
        reset_data(output_dir)
        state_file = output_dir / BACKLOG_STATE_FILE
        if state_file.exists():
            state_file.unlink()
            print(f"  Deleted: {state_file}")
        print("\nReset complete. Run without --reset to process commits.")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    branch = args.branch or fetch_default_branch(args.repo, token=args.token)

    print(f"Repo:   {args.repo}")
    print(f"Branch: {branch}")
    print(f"Output: {output_dir}\n")

    # ── Fetch commits ─────────────────────────────────────────────────────────

    backlog_date      = None
    unprocessed_count = None   # set before limit; used for backlog advance logic

    if args.today:
        # Rolling 24-hour window ending now
        since = (datetime.utcnow() - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
        print(f"Mode:   today (last 24 hours since {since})\n")
        print("Fetching commits from GitHub...")
        all_commits = fetch_github_commits(args.repo, token=args.token, since=since, branch=branch)
        verboseprint(f"Total commits fetched: {len(all_commits)}")

    elif args.backlog:
        print("Mode:   backlog\n")
        MAX_SEARCH = 90
        backlog_date = load_backlog_date(output_dir)
        for _ in range(MAX_SEARCH):
            since           = f"{backlog_date.isoformat()}T00:00:00Z"
            until           = f"{(backlog_date + timedelta(days=1)).isoformat()}T00:00:00Z"
            print(f"Fetching commits for {backlog_date}...")
            all_commits     = fetch_github_commits(args.repo, token=args.token, since=since, until=until, branch=branch)
            verboseprint(f"  Got {len(all_commits)} commits for {backlog_date}")

            noted_sha7s     = get_noted_sha7s(notes_path)
            skipped_sha7s   = get_skipped_sha7s(output_dir)
            processed_sha7s = noted_sha7s | skipped_sha7s
            pending         = [c for c in all_commits if c['sha'][:7] not in processed_sha7s]

            if pending:
                break

            next_date = backlog_date - timedelta(days=1)
            if not args.dry_run:
                save_backlog_date(output_dir, next_date)
            print(f"  {backlog_date}: nothing to process — advancing to {next_date}")
            backlog_date = next_date
        else:
            print(f"\nNo unprocessed commits found in the last {MAX_SEARCH} days.")
            return

    else:
        # Default: all unprocessed, newest fetch window capped to avoid rate limits
        fetch_cap = max(100, args.limit * 4) if args.limit else None
        if fetch_cap:
            verboseprint(f"Fetch cap: {fetch_cap} commits (--limit {args.limit} * 4)")
        print("Fetching commits from GitHub...")
        all_commits = fetch_github_commits(args.repo, token=args.token, max_commits=fetch_cap, branch=branch)
        verboseprint(f"Total commits fetched: {len(all_commits)}")

    # ── Filter to unprocessed ─────────────────────────────────────────────────

    if not args.backlog:
        # Backlog mode already computed these inside the search loop above
        noted_sha7s     = get_noted_sha7s(notes_path)
        skipped_sha7s   = get_skipped_sha7s(output_dir)
        processed_sha7s = noted_sha7s | skipped_sha7s
        pending         = [c for c in all_commits if c['sha'][:7] not in processed_sha7s]

    verboseprint(f"SHA7s in release notes: {noted_sha7s}")
    verboseprint(f"SHA7s marked skip in DB: {skipped_sha7s}")

    new_commits       = list(reversed(pending))   # oldest first
    unprocessed_count = len(new_commits)           # before limit

    if args.limit:
        verboseprint(f"--limit {args.limit} applied: trimming from {unprocessed_count} to {min(args.limit, unprocessed_count)} commits")
        new_commits = new_commits[:args.limit]

    scope_label   = "in window" if (args.today or args.backlog) else "in repo"
    total_noted   = len(noted_sha7s)
    total_skipped = len(skipped_sha7s)
    total_new     = len(new_commits)
    print(f"  {len(all_commits)} {scope_label}  ·  {total_noted} noted  ·  {total_skipped} skipped  ·  {total_new} to process\n")

    if not new_commits:
        print("Nothing to do — all commits already have release notes.")
        if args.backlog and backlog_date is not None and not args.dry_run:
            next_date = backlog_date - timedelta(days=1)
            save_backlog_date(output_dir, next_date)
            print(f"  Backlog: {backlog_date} complete. Next run will process {next_date}.")
        return

    if args.dry_run:
        print("Dry run — commits that would be processed (oldest first):")
        for c in new_commits:
            sha7 = c['sha'][:7]
            date = c['commit']['author']['date'][:10]
            msg  = c['commit']['message'].splitlines()[0][:70]
            print(f"  {sha7}  {date}  {msg}")
        return

    print(f"Processing {total_new} commit{'s' if total_new != 1 else ''} (oldest first):\n")

    _stats_path  = output_dir / "orchestrator_stats.jsonl"
    _stats_start = stats_start_line(_stats_path)

    succeeded = 0
    failed    = []
    for i, commit in enumerate(new_commits, 1):
        sha7 = commit['sha'][:7]
        date = commit['commit']['author']['date'][:10]
        msg  = commit['commit']['message'].splitlines()[0][:70]
        url  = f"https://github.com/{args.repo}/commit/{commit['sha']}"

        bar = "━" * 60
        print(bar)
        print(f"  [{i}/{total_new}]  {sha7}  {date}")
        print(f"  {msg}")
        print(bar + "\n")

        ok = run_orchestrator(url, args.orchestrator, output_dir,
                              verbose=args.verbose, security=args.security, branch=branch)
        if ok:
            succeeded += 1
            verboseprint(f"Commit {sha7} succeeded ({succeeded} done, {len(failed)} failed so far)")
        else:
            failed.append(sha7)
            verboseprint(f"Commit {sha7} FAILED (exit non-zero) ({succeeded} done, {len(failed)} failed so far)")
        print()

    print_pipeline_summary(_stats_path, _stats_start, succeeded, failed)

    # ── Backlog date advance ──────────────────────────────────────────────────
    if args.backlog and backlog_date is not None:
        limit_hit = args.limit and unprocessed_count > args.limit
        if limit_hit:
            remaining = unprocessed_count - args.limit
            print(f"  Backlog: {remaining} commit{'s' if remaining != 1 else ''} still pending for {backlog_date}. Run again to continue.")
        else:
            next_date = backlog_date - timedelta(days=1)
            save_backlog_date(output_dir, next_date)
            print(f"  Backlog: {backlog_date} complete. Next run will process {next_date}.")

def main():
    try:
        run()
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit('\nUser canceled... Stopping\n')
    except Exception as e:
        print('An unexpected error occurred: %s' % str(e), file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
