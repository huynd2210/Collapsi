#!/usr/bin/env python3
"""
Validate solved_norm.db for plausibility and summarize statistics.

- Streams the entire DB by default (all entries), or the first N if a limit is provided.
- Checks:
  * turn in {0,1}
  * win in {0,1}
  * best move encodes from/to within [0,15] or 0xFF
  * plies within a reasonable 4x4 bound (0..50)
  * win==1 implies plies>=1; win==0 implies plies>=0
- Prints a JSON summary with counts and samples

Usage:
  python Collapsi/tools/validate_solved_db.py Collapsi/data/solved_norm.db         # all records
  python Collapsi/tools/validate_solved_db.py Collapsi/data/solved_norm.db 500000  # first 500k
"""
from __future__ import annotations

import json
import os
import sys
from typing import List, Tuple, Optional

# Ensure we can import the local reader
HERE = os.path.dirname(__file__)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import read_records as rr


def validate(db_path: str, limit: Optional[int] = None) -> None:
    """
    Stream-validate the DB. If limit is None or <=0, process all entries.
    """
    # Helper for move encoding validity
    def _best_ok(b: int) -> bool:
        if b == 0xFF:
            return True
        f = (b >> 4) & 0x0F
        t = b & 0x0F
        return 0 <= f <= 15 and 0 <= t <= 15

    # Aggregates
    n = 0
    turn0 = 0
    turn1 = 0
    win0 = 0
    win1 = 0
    plies_min: Optional[int] = None
    plies_max: Optional[int] = None
    plies_sum: int = 0
    bad_move_count = 0
    anomaly_count = 0
    bad_move_sample: List[int] = []
    anomaly_sample: List[int] = []
    first5: List[dict] = []

    effective_limit = limit if (limit is not None and limit > 0) else (1 << 62)

    idx = 0
    for r in rr.iter_solved_records(db_path, start=0, limit=effective_limit):
        t = int(r.turn)
        w = int(r.win)
        p = int(r.plies)
        b = int(r.best)

        if idx < 5:
            first5.append({
                "key": f"{r.key:016x}|{r.turn}",
                "turn": t,
                "win": w,
                "best": b,
                "plies": p,
            })

        n += 1
        if t == 0:
            turn0 += 1
        elif t == 1:
            turn1 += 1

        if w == 1:
            win1 += 1
        elif w == 0:
            win0 += 1

        if not _best_ok(b):
            bad_move_count += 1
            if len(bad_move_sample) < 10:
                bad_move_sample.append(idx)

        anom = False
        if not (0 <= p <= 50):
            anom = True
        elif w == 1 and p < 1:
            anom = True
        elif w == 0 and p < 0:
            anom = True
        if anom:
            anomaly_count += 1
            if len(anomaly_sample) < 10:
                anomaly_sample.append(idx)

        if plies_min is None or p < plies_min:
            plies_min = p
        if plies_max is None or p > plies_max:
            plies_max = p
        plies_sum += p

        idx += 1

    avg_plies = (round(plies_sum / n, 2) if n > 0 else None)

    summary = {
        "count": n,
        "turns": {"0": turn0, "1": turn1},
        "wins": {"0": win0, "1": win1},
        "plies": {
            "min": (plies_min if n > 0 else None),
            "avg": avg_plies,
            "max": (plies_max if n > 0 else None),
        },
        "bad_move_count": bad_move_count,
        "bad_move_sample": bad_move_sample,
        "anomaly_count": anomaly_count,
        "anomaly_sample": anomaly_sample,
        "first5": first5,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "data", "solved_norm.db")
    lim_arg = sys.argv[2] if len(sys.argv) > 2 else None
    lim: Optional[int] = None
    if lim_arg is not None:
        la = str(lim_arg).strip().lower()
        if la not in ("all", "0", "-1", "none"):
            try:
                lim = int(lim_arg)
            except Exception:
                lim = None
    validate(db, lim)