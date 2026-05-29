#!/usr/bin/env python3
# fetch_commit_data.py — CLI wrapper around release_tools.fetch_commit_data()
# Usage: python3 tools/fetch_commit_data.py <sha>

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tools.release_tools import fetch_commit_data

if len(sys.argv) < 2:
    sys.exit("Usage: fetch_commit_data.py <sha>")

data = fetch_commit_data(sys.argv[1])
print(f"SHA:     {data['sha']}")
print(f"SHA7:    {data['sha7']}")
print(f"Repo:    {data['repo']}")
print(f"URL:     {data['url']}")
print(f"Message: {data['message']}")
print(f"Author:  {data['author']}")
print(f"Date:    {data['date']}")
print(f"\nFiles changed ({len(data['files'])}):")
for f in data['files']:
    print(f"  [{f['status']}] {f['filename']} (+{f['additions']}/-{f['deletions']})")
    if f['patch']:
        print(f"  Patch:\n{f['patch']}\n")
