#!/usr/bin/env python3
# save_product_data.py
#
# CLI wrapper to insert one product row.
# Primarily a debugging aid; agents use shopping_tools directly via import.
# Usage:
#   python3 tools/save_product_data.py --query "..." --index 0 --url "..." \
#       --title "..." --price "$299" --summary "..." --pros "- a\n- b" \
#       --cons "- x" --availability "In stock" --purchase-url "..." \
#       --raw-snippet "..."

import sys
import argparse
sys.path.insert(0, '.')

from ShoppingAssistant.tools.shopping_tools import save_product_data

parser = argparse.ArgumentParser()
parser.add_argument('--query',        required=True)
parser.add_argument('--index',        type=int, required=True)
parser.add_argument('--url',          required=True)
parser.add_argument('--title',        required=True)
parser.add_argument('--price',        required=True)
parser.add_argument('--summary',      required=True)
parser.add_argument('--pros',         required=True)
parser.add_argument('--cons',         required=True)
parser.add_argument('--availability', required=True)
parser.add_argument('--purchase-url', required=True)
parser.add_argument('--raw-snippet',  required=True)
args = parser.parse_args()

product_id = save_product_data(
    search_query=args.query,
    result_index=args.index,
    url=args.url,
    title=args.title,
    price=args.price,
    summary=args.summary,
    pros=args.pros,
    cons=args.cons,
    availability=args.availability,
    purchase_url=args.purchase_url,
    raw_snippet=args.raw_snippet,
)
print(f'Saved product_id: {product_id}')
