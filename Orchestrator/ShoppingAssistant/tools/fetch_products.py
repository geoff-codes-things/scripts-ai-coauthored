#!/usr/bin/env python3
# fetch_products.py
#
# CLI: print all researched products, or just the count.
# Usage:
#   python3 tools/fetch_products.py
#   python3 tools/fetch_products.py --count

import sys
import argparse
sys.path.insert(0, '.')

from ShoppingAssistant.tools.shopping_tools import fetch_all_products, fetch_product_count

parser = argparse.ArgumentParser()
parser.add_argument('--count', action='store_true', help='Print only the product count')
args = parser.parse_args()

if args.count:
    print(fetch_product_count())
else:
    products = fetch_all_products()
    if not products:
        print('(no products found)')
    else:
        print(f'{len(products)} product(s) in database:\n')
        for p in products:
            print(f"[{p['product_id']}] {p['title']} — {p['price']}")
            print(f"  URL:          {p['url']}")
            print(f"  Purchase URL: {p['purchase_url']}")
            print(f"  Availability: {p['availability']}")
            print(f"  Summary:      {p['summary']}")
            print(f"  Pros: {p['pros']}")
            print(f"  Cons: {p['cons']}")
            print()
