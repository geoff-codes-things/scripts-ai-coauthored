#!/usr/bin/env python3
# fetch_report.py
#
# CLI: print the latest report content, or just its status.
# Usage:
#   python3 tools/fetch_report.py
#   python3 tools/fetch_report.py --status

import sys
import argparse
sys.path.insert(0, '.')

from ShoppingAssistant.tools.shopping_tools import fetch_latest_report

parser = argparse.ArgumentParser()
parser.add_argument('--status', action='store_true', help='Print only status and revision notes')
args = parser.parse_args()

rpt = fetch_latest_report()
if not rpt:
    print('(no report found)')
elif args.status:
    print(f"report_id: {rpt['report_id']}")
    print(f"iteration: {rpt['iteration']}")
    print(f"status:    {rpt['status']}")
    if rpt.get('revision_notes'):
        print(f"revision_notes:\n{rpt['revision_notes']}")
else:
    print(f"report_id: {rpt['report_id']}  iteration: {rpt['iteration']}  status: {rpt['status']}")
    print()
    print(rpt['content'])
