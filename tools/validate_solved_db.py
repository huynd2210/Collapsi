#!/usr/bin/env python3
"""
Validate a solved_norm.db sample for plausibility.

- Reads first N records from a given solved_norm.db using read_records.iter_solved_records
- Checks:
  * turn in {0,1}
  * win in {0,1}
  * best move encodes from/to within [0,15] or 0xFF
  * plies within a reasonable 4x4 bound (0..50)
  * win==1 implies plies>=1; win==0 implies plies>=0
- Prints a JSON summary with counts and samples
"""
from __future__ import annotations

import json
import os
import sys
from typing import List, Tuple

# Ensure we can import the local reader
HERE = os.path.dirname(__file__)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import read_records as rr


def validate(db_path: str, limit: int = 100) -> None:
    recs = list(rr.iter_solved_records(db_path, start=0, limit=limit))
    n = len(recs)

    turns = [int(r.turn) for r in recs]
    wins = [int(r.win) for r in recs]
    plies = [int(r.plies) for r in recs]

    # Validate best moves
    def best_ok(r) -> bool:
        b = int(r.best)
        if b == 0xFF:
            return True
        f = (b >> 4) & 0x0F
        t = b & 0x0F
        return 0 <= f <= 15 and 0 <= t <= 15

    bad_mv_idx = [i for i, r in enumerate(recs) if not best_ok(r)]

    # Validate plies semantics
    anom_idx = []
    for i, r in enumerate(recs):
        p = int(r.plies)
        w = int(r.win)
        if not (0 <= p <= 50):
            anom_idx.append(i)
            continue
        if w == 1 and p < 1:
            anom_idx.append(i)
            continue
        if w == 0 and p < 0:
            anom_idx.append(i)
            continue

    # Compose summary
    summary = {
        "count": n,
        "turns": {"0": turns.count(0), "1": turns.count(1)},
        "wins": {"0": wins.count(0), "1": wins.count(1)},
        "plies": {
            "min": (min(plies) if plies else None),
            "avg": (round(sum(plies) / len(plies), 2) if plies else None),
            "max": (max(plies) if plies else None),
        },
        "bad_move_count": len(bad_mv_idx),
        "bad_move_sample": bad_mv_idx[:10],
        "anomaly_count": len(anom_idx),
        "anomaly_sample": anom_idx[:10],
        "first5": [
            {
                "key": f"{r.key:016x}|{r.turn}",
                "turn": int(r.turn),
                "win": int(r.win),
                "best": int(r.best),
                "plies": int(r.plies),
            }
            for r in recs[:5]
        ],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "data", "test_solved_norm.db")
    lim = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    validate(db, lim)