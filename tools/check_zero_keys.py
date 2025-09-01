#!/usr/bin/env python3
"""
Check for zero (all-zeros) keys in a solved_norm.db file.

Usage:
  python Collapsi/tools/check_zero_keys.py data/test_solved_norm.db 100
  python Collapsi/tools/check_zero_keys.py Collapsi/data/solved_norm.db 1000
"""
from __future__ import annotations
import os, sys

HERE = os.path.dirname(__file__)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import read_records as rr  # uses iter_solved_records

def main() -> int:
    if len(sys.argv) < 2:
        print("usage: check_zero_keys.py <db_path> [limit]")
        return 2
    db = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    if not os.path.exists(db):
        print(f"{db} MISSING")
        return 1
    zeros = []
    total = 0
    for rec in rr.iter_solved_records(db, start=0, limit=limit):
        if rec.key == 0:
            zeros.append(total)
        total += 1
    print(f"db={db} total_read={total} zero_count={len(zeros)} zero_indices={zeros[:50]}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())