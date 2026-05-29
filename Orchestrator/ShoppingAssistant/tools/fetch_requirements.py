#!/usr/bin/env python3
# fetch_requirements.py
#
# CLI: print current session requirements, or save raw Q&A answers.
# Usage:
#   python3 tools/fetch_requirements.py
#   python3 tools/fetch_requirements.py --save-raw "Q: ...\nA: ..."

import sys
import argparse
sys.path.insert(0, '.')

from ShoppingAssistant.tools.shopping_tools import fetch_requirements, save_raw_answers

parser = argparse.ArgumentParser()
parser.add_argument('--save-raw', metavar='TEXT', default=None,
                    help='Save raw Q&A answers to session')
args = parser.parse_args()

if args.save_raw:
    save_raw_answers(args.save_raw)
else:
    data = fetch_requirements()
    if not data:
        print('(no session found)')
    else:
        print(f"Status:   {data['status']}")
        print(f"Requirements:\n{data['requirements'] or '(none yet)'}")
        if data.get('pending_question'):
            print(f"Pending question: {data['pending_question']}")
        print(f"\nRaw answers:\n{data['raw_answers'] or '(none)'}")
