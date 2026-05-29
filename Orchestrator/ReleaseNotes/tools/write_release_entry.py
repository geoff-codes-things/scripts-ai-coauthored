#!/usr/bin/env python3
# write_release_entry.py — CLI wrapper around release_tools.write_release_entry()
# Usage: python3 tools/write_release_entry.py <sha> <summary> <change_type>

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tools.release_tools import write_release_entry, VALID_TYPES

if len(sys.argv) < 4:
    sys.exit(f'Usage: write_release_entry.py <sha> "<summary>" "<change_type>"\nchange_type must be one of: {VALID_TYPES}')

print(write_release_entry(sys.argv[1], sys.argv[2], sys.argv[3]))
