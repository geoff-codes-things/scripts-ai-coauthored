#!/usr/bin/env python3
# shopping_pipeline.py
#
# Shopping assistant pipeline: collects requirements, searches the web,
# extracts product data, generates a verified comparison report, and
# produces a self-contained HTML presentation.
#
# Usage:
#   python shopping_pipeline.py --name wireless-headphones
#   python shopping_pipeline.py --name coffee-grinder --skip-research
#   python shopping_pipeline.py --name my-search --reset

import argparse
import sys
import os
import re
import json
import subprocess
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent          # Orchestrator/ShoppingAssistant/
TOP_DIR    = SCRIPT_DIR.parent              # Orchestrator/
AGENTS_DIR = SCRIPT_DIR / "agents"
BASE_OUTPUT = SCRIPT_DIR / "output"

sys.path.insert(0, str(TOP_DIR))

MAX_REVISION_ITERATIONS = 3
MAX_QUESTIONS = 10

# ============= ARGUMENTS =============

parser = argparse.ArgumentParser(
    description="Shopping assistant: research products and generate a comparison report.",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""Examples:
  python shopping_pipeline.py --name coffee-grinder
  python shopping_pipeline.py --name headphones --skip-research
  python shopping_pipeline.py --name coffee-grinder --reset
  python shopping_pipeline.py --name coffee-grinder --security medium -v
"""
)
parser.add_argument("--name", required=True,
                    help="Project name — used as the output subdirectory.",
                    metavar="NAME")
parser.add_argument("--orchestrator", default=str(TOP_DIR / "orchestrator.py"),
                    help="Path to orchestrator.py.",
                    metavar="PATH")
parser.add_argument("--model", default=None,
                    help="Model name to pass to the orchestrator (e.g. qwen/qwen3.5-35b-a3b). Auto-detected if not provided.",
                    metavar="MODEL")
parser.add_argument("--security", choices=["low", "medium", "high"], default="low",
                    help="Security level for the orchestrator. (default: low)")
parser.add_argument("--skip-research", action="store_true",
                    help="Skip requirements collection and research; go straight to report generation.")
parser.add_argument("--reset", action="store_true",
                    help="Delete all data for this project and start fresh.")
parser.add_argument("--max-results", type=int, default=5,
                    help="DuckDuckGo results to fetch per query. (default: 5)")
parser.add_argument("-v", "--verbose", action="store_true",
                    help="Enable verbose orchestrator output.")
parser.add_argument("--responses", metavar="FILE",
                    help="JSON file with pre-filled answers to bypass interactive prompts.")

# ============= CONSOLE OUTPUT =============

def verbosePrintSetup(verbosestate):
    if verbosestate:
        def verboseprintfunc(*args):
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}]", *args)
        return verboseprintfunc
    return lambda *args: None

verboseprint = lambda *a: None

W = 60

def banner(title):
    print("═" * W)
    print(f"  {title}")
    print("═" * W)

def section(title):
    print(f"\n── {title} {'─' * max(0, W - len(title) - 4)}")

# ============= ORCHESTRATOR RUNNER =============

def run_orchestrator(task, output_dir, capture=False):
    stats_path = output_dir / "orchestrator_stats.jsonl"
    cmd = [
        sys.executable, str(TOP_DIR / "orchestrator.py"),
        "--task", task,
        "--agents-dir", str(AGENTS_DIR),
        "--stats-path", str(stats_path),
        "--no-synthesis",
        "--loop",
    ]
    if args.model:
        cmd.extend(["--model", args.model])
    if args.security != "low":
        cmd.extend(["--security", args.security])
    if args.verbose:
        cmd.append("-v")

    env = os.environ.copy()
    env["SHOPPING_OUTPUT_DIR"] = str(output_dir)

    verboseprint(f"Task: {task[:80]}...")

    if capture:
        result = subprocess.run(cmd, cwd=str(TOP_DIR), env=env,
                                capture_output=True, text=True)
        verboseprint(f"Exit code: {result.returncode}")
        return result.returncode, result.stdout + result.stderr
    else:
        result = subprocess.run(cmd, cwd=str(TOP_DIR), env=env)
        verboseprint(f"Exit code: {result.returncode}")
        return result.returncode, None

# ============= QUERY GENERATION =============

def generate_search_queries(requirements_text):
    text = requirements_text.lower()
    product_type = "product"
    price_hint = ""

    # Separate answer lines from question lines so price hints in example prompts don't bleed in
    answer_lines = []
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('a:'):
            answer_lines.append(stripped[2:].strip())
    answers_only = ' '.join(answer_lines)

    # Strategy 1: extract product from first answer line in Q&A transcript
    if answer_lines:
        candidate = answer_lines[0]
        candidate = re.sub(r'\b(a |an |the |new |another |some |my |one |get |buy )', ' ', candidate)
        candidate = re.sub(r'\s+', ' ', candidate).strip()
        candidate = candidate.split('.')[0].split(',')[0].strip()
        if 3 < len(candidate) < 60:
            product_type = candidate

    # Strategy 2: formatted requirements summary (no Q:/A: structure)
    if product_type == "product":
        for phrase in [
            r'(?:looking for|want|need|shopping for|searching for) (?:a |an )?([a-z][a-z ]{2,40}?)(?:\.|,| for| under| around| that|\n|$)',
            r'(?:product category|category)[:\s]+([a-z][a-z ]{2,30}?)(?:\.|,|\n|$)',
        ]:
            m = re.search(phrase, text)
            if m:
                candidate = m.group(1).strip().rstrip('.,')
                if 2 < len(candidate) < 50:
                    product_type = candidate
                    break

    # Extract price hint from answers only (avoids matching example text in questions)
    price_source = answers_only if answers_only else text
    price_m = re.search(
        r'under \$?([\d,]+)|around \$?([\d,]+)|\$?([\d,]+)\s*[-–to]+\s*\$?([\d,]+)',
        price_source
    )
    if price_m:
        nums = [g for g in price_m.groups() if g]
        if nums:
            price_hint = f"under ${nums[-1].replace(',', '')}"
    elif any(w in price_source for w in ['mid range', 'mid-range', 'mid priced', 'mid-priced', 'moderate', 'midrange']):
        price_hint = "mid range"
    elif any(w in price_source for w in ['budget', 'cheap', 'affordable', 'inexpensive']):
        price_hint = "budget"

    year = datetime.now().year
    base = product_type

    queries = [
        f"best {base} {price_hint}".strip(),
        f"{base} review {year}",
        f"top {base} comparison",
    ]

    # Add a feature-specific query based on mentioned keywords
    feature_keywords = [
        ('easy to clean', f"easy to clean {base}"),
        ('small', f"compact {base}"),
        ('portable', f"portable {base}"),
        ('quiet', f"quiet {base}"),
        ('wireless', f"best wireless {base}"),
        ('noise cancell', f"noise cancelling {base}"),
        ('beginner', f"{base} for beginners"),
        ('drip', f"{base} for drip coffee"),
        ('espresso', f"{base} for espresso"),
    ]
    for keyword, extra_query in feature_keywords:
        if keyword in text:
            queries.append(extra_query)
            break

    # Deduplicate
    seen = set()
    unique = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique.append(q)

    return unique[:5]

# ============= RESET =============

def reset_project(output_dir):
    import shutil
    if output_dir.exists():
        shutil.rmtree(output_dir)
        print(f"Deleted: {output_dir}")
    print("Reset complete.")

# ============= MAIN PIPELINE =============

def run():
    global args, verboseprint
    args = parser.parse_args()
    verboseprint = verbosePrintSetup(args.verbose)

    output_dir = BASE_OUTPUT / args.name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load tools with the correct output dir set
    os.environ["SHOPPING_OUTPUT_DIR"] = str(output_dir)
    from ShoppingAssistant.tools.shopping_tools import (
        save_raw_answers, fetch_requirements, fetch_product_count,
        fetch_all_products, fetch_latest_report, run_ddg_search,
        fetch_candidates, fetch_candidate_count
    )

    if args.reset:
        reset_project(output_dir)
        print("\nRun without --reset to start a new session.")
        return

    banner(f"Shopping Assistant — {args.name}")

    # ── PHASE 1: Requirements collection ─────────────────────────────────────
    if not args.skip_research:
        section("Requirements Collection")

        prefilled = {}
        if args.responses:
            with open(args.responses) as f:
                prefilled = json.load(f)
            print(f"Using pre-filled responses from: {args.responses}\n")
        else:
            print("Answer the questions below. Press Enter to skip any optional one.\n")

        transcript_lines = []

        # Ask a batch of standard questions upfront — no orchestrator call yet
        std_questions = [
            ("What are you shopping for?",            True,  "product"),
            ("Budget / price range (e.g. under $100, mid-range):", False, "budget"),
            ("Key features or requirements:",          False, "features"),
            ("Main use case:",                         False, "use_case"),
            ("Size, compatibility, or other constraints:", False, "constraints"),
        ]
        for question, required, key in std_questions:
            if key in prefilled:
                answer = prefilled[key]
                print(f"  {question} {answer}")
            else:
                answer = input(f"  {question} ").strip()
            if answer or required:
                transcript_lines.append(f"Q: {question}")
                transcript_lines.append(f"A: {answer if answer else '(not specified)'}")

        transcript = "\n".join(transcript_lines)
        save_raw_answers(transcript)

        # Single orchestrator call to validate and formalize
        print("\n  (Reviewing requirements...)")
        run_orchestrator(
            "Review the shopping Q&A transcript and determine if requirements are complete",
            output_dir
        )

        session = fetch_requirements()
        requirements_complete = session and session.get("status") == "complete"

        # If incomplete, ask the follow-up questions all at once (one more pass)
        if not requirements_complete and session and session.get("pending_question"):
            pending_raw = session["pending_question"]
            # Parse lines starting with "-" or numbered "1."
            follow_ups = [
                re.sub(r'^[-\d\.\s]+', '', line).strip()
                for line in pending_raw.split('\n')
                if line.strip() and not line.strip().startswith('FILL_IN')
            ]
            follow_ups = [q for q in follow_ups if len(q) > 5]

            if follow_ups and not prefilled:
                print("\n  A few more details:\n")
                for q in follow_ups:
                    answer = input(f"  {q} ").strip()
                    if answer:
                        transcript_lines.append(f"Q: {q}")
                        transcript_lines.append(f"A: {answer}")

                transcript = "\n".join(transcript_lines)
                save_raw_answers(transcript)

                print("\n  (Finalizing requirements...)")
                run_orchestrator(
                    "Review the shopping Q&A transcript and determine if requirements are complete",
                    output_dir
                )
                session = fetch_requirements()
                requirements_complete = session and session.get("status") == "complete"

        if requirements_complete and session:
            print(f"\n  Requirements confirmed:\n  {session.get('requirements', '').replace(chr(10), chr(10) + '  ')}")
        else:
            print("\n  Proceeding with available requirements.")

        # ── PHASE 2: Query generation ─────────────────────────────────────────
        section("Generating Search Queries")
        session = fetch_requirements()
        reqs_text = (session.get("raw_answers") or session.get("requirements") or "") if session else ""
        queries = generate_search_queries(reqs_text)
        print(f"  Generated {len(queries)} search queries:")
        for q in queries:
            print(f"    • {q}")

        # ── PHASE 3a: Scout — identify candidate product model names ─────────
        section("Scouting Product Candidates")

        all_snippets = []
        for query in queries:
            print(f"  Searching: \"{query}\"")
            try:
                results = run_ddg_search(query, max_results=args.max_results)
            except Exception as e:
                print(f"  Search error: {e}")
                continue
            for result in results:
                all_snippets.append({
                    "title": result.get('title', ''),
                    "body":  result.get('body', ''),
                })

        if not all_snippets:
            print("\nNo search results found — cannot proceed.")
            return

        print(f"\n  Collected {len(all_snippets)} snippets. Identifying product candidates...")
        scout_file = output_dir / "_scout_snippets.json"
        with open(scout_file, 'w', encoding='utf-8') as f:
            json.dump({'count': len(all_snippets), 'snippets': all_snippets}, f,
                      ensure_ascii=False, indent=2)
        run_orchestrator(
            "Identify product model names from search result snippets and save each as a research candidate",
            output_dir
        )
        if scout_file.exists():
            scout_file.unlink()

        candidate_count = fetch_candidate_count()
        print(f"\n  Scouting complete: {candidate_count} candidate product(s) identified.")

        if candidate_count == 0:
            print("\nNo product candidates found — cannot proceed to detailed research.")
            print("Try running with different search terms or check your internet connection.")
            return

        # ── PHASE 3b: Research — targeted search per candidate ────────────────
        section("Researching Product Details")

        candidates = fetch_candidates(unresearched_only=True)
        print(f"  Researching {len(candidates)} product(s)...\n")

        for cand in candidates:
            model_name = cand['model_name']
            print(f"  Researching: {model_name}")
            search_query = f"{model_name} review price buy"
            try:
                results = run_ddg_search(search_query, max_results=args.max_results)
            except Exception as e:
                print(f"    Search error: {e}")
                continue

            if not results:
                print(f"    No results for {model_name}.")
                continue

            # Write to a fixed filename — plan cache must not carry a path with spaces/ID
            results_file = output_dir / "_research_current.json"
            with open(results_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'model_name': model_name,
                    'query': search_query,
                    'results': results
                }, f, ensure_ascii=False)

            run_orchestrator("Read the queued product search results and save the product record to the database", output_dir)

        # Clean up temp research file
        research_tmp = output_dir / "_research_current.json"
        if research_tmp.exists():
            research_tmp.unlink()

        product_count = fetch_product_count()
        print(f"\n  Research complete: {product_count} product(s) fully researched.")

        if product_count == 0:
            print("\nNo products found in research phase — cannot generate report.")
            print("Try running with different search terms or check your internet connection.")
            return

    else:
        section("Skipping Research (--skip-research)")
        product_count = fetch_product_count()
        print(f"  Products already in database: {product_count}")
        if product_count == 0:
            print("No products in database. Remove --skip-research to run research phase.")
            return

    # ── PHASE 4: Report generation + accuracy check loop ─────────────────────
    section("Generating Comparison Report")
    revision_notes = None

    for iteration in range(1, MAX_REVISION_ITERATIONS + 1):
        print(f"\n  Writing report (iteration {iteration})...")

        if revision_notes:
            task = (
                f"Write a shopping comparison report for iteration {iteration}. "
                f"Address these revision notes from the previous draft: {revision_notes}"
            )
        else:
            task = f"Write a shopping comparison report for iteration {iteration}"

        run_orchestrator(task, output_dir)

        print(f"  Checking accuracy (iteration {iteration})...")
        run_orchestrator(
            "Check the shopping comparison report for accuracy against the research data",
            output_dir
        )

        rpt = fetch_latest_report()
        if not rpt:
            print("  No report found after generation — something went wrong.")
            break

        status = rpt.get("status", "")
        if status == "approved":
            print(f"  Report approved on iteration {iteration}.")
            break
        elif status == "needs_revision":
            revision_notes = rpt.get("revision_notes", "")
            print(f"  Revision needed:\n{revision_notes}")
            if iteration == MAX_REVISION_ITERATIONS:
                print("  Max iterations reached — using best available report.")
        else:
            print(f"  Unexpected status '{status}' — using report as-is.")
            break

    # ── PHASE 5: Write JSON snapshot and generate HTML ────────────────────────
    section("Generating Final Output")

    rpt = fetch_latest_report()
    if not rpt:
        print("No report available — cannot generate output.")
        return

    # Write the verified JSON to disk
    json_path = output_dir / "SHOPPING_REPORT.json"
    try:
        report_obj = json.loads(rpt["content"])
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_obj, f, indent=2)
        print(f"  JSON report: {json_path}")

        # Also write the verified copy for the presenter
        verified_path = output_dir / "SHOPPING_REPORT_verified.json"
        with open(verified_path, "w", encoding="utf-8") as f:
            json.dump(report_obj, f, indent=2)
    except Exception as e:
        print(f"  Warning: could not parse report JSON: {e}")

    print("\n  Generating HTML presentation...")
    run_orchestrator(
        "Generate an HTML presentation of the approved shopping comparison report",
        output_dir
    )

    html_path = output_dir / "SHOPPING_REPORT.html"
    if html_path.exists():
        print(f"\n  HTML report: {html_path}")
    else:
        print("\n  HTML file not found — check orchestrator output above.")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    banner("Done")
    print(f"  Output directory: {output_dir}")
    if html_path.exists():
        print(f"  Open in browser:  file://{html_path}")
    print()


def main():
    run()

if __name__ == "__main__":
    main()
