#!/usr/bin/env python3
# save_report_data.py
#
# CLI wrapper to insert a report or update its status.
# Primarily a debugging aid; agents use shopping_tools directly via import.
# Usage:
#   python3 tools/save_report_data.py --iteration 1 --content '{"products": [...]}'
#   python3 tools/save_report_data.py --update-status 3 --status approved
#   python3 tools/save_report_data.py --update-status 3 --status needs_revision --notes "- Product A: wrong price"

import sys
import argparse
sys.path.insert(0, '.')

from ShoppingAssistant.tools.shopping_tools import save_report, update_report_status

parser = argparse.ArgumentParser()
parser.add_argument('--iteration',     type=int, default=None)
parser.add_argument('--content',       default=None)
parser.add_argument('--update-status', type=int, default=None, metavar='REPORT_ID')
parser.add_argument('--status',        default=None)
parser.add_argument('--notes',         default=None)
args = parser.parse_args()

if args.update_status is not None:
    if not args.status:
        print('--status required with --update-status', file=sys.stderr)
        sys.exit(1)
    update_report_status(args.update_status, args.status, args.notes)
elif args.iteration is not None and args.content:
    report_id = save_report(args.content, args.iteration)
    print(f'Saved report_id: {report_id}')
else:
    print('Provide either (--iteration + --content) or (--update-status + --status)', file=sys.stderr)
    sys.exit(1)
