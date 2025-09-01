#!/usr/bin/env python3
"""
Record reader for Collapsi solved_norm.db and optional norm_index.db.

- Reads binary records of normalized solved states:
  key(u64), turn(u8), win(u8), best(u8), plies(u16), pad (auto-detected)
- Optionally prints a 4x4 overlay board if norm_index.db is provided
- Optionally lists all raw torus-shifted keys via norm2raw/*.txt
- Outputs in text or JSON

Usage examples:
  python Collapsi/tools/read_records.py --db data/solved_norm.db --limit 5
  python Collapsi/tools/read_records.py --db Collapsi/data/solved_norm.db --index Collapsi/data/norm_index.db --board --limit 3
  python Collapsi/tools/read_records.py --db Collapsi/data/solved_norm.db --index Collapsi/data/norm_index.db --board --norm2raw Collapsi/cpp/data/norm2raw --raw-keys --limit 1
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple


# ---------- Utilities ----------

def human_key(key: int, turn: int) -> str:
    return f"{key:016x}|{turn}"


def idx_to_rc(idx: int) -> Tuple[int, int]:
    return (idx // 4, idx % 4)


def decode_move(best: int) -> Optional[Tuple[int, int, int, int]]:
    """
    Decode (from,to) from encoded uint8 ((from<<4)|to) into (rf,cf,rt,ct).
    Returns None if best==0xFF.
    """
    if best == 0xFF:
        return None
    f = (best & 0xF0) >> 4
    t = best & 0x0F
    rf, cf = idx_to_rc(f)
    rt, ct = idx_to_rc(t)
    return rf, cf, rt, ct


# ---------- Binary layout: solved_norm.db ----------

@dataclass
class SolvedRecord:
    key: int
    turn: int  # 0 X, 1 O
    win: int   # 0/1
    best: int  # uint8, 0xFF means none
    plies: int # uint16


def _score_solved_format(path: str, fmt: str, rec_size: int, max_samples: int = 512) -> float:
    """
    Heuristic scoring for format detection.
    Checks the first N records and counts how many have plausible fields:
      - turn in {0,1}
      - win in {0,1}
      - best encodes from/to in [0,15] OR equals 0xFF
      - plies plausibility on 4x4: 0 <= plies <= 50, and (win==1 => plies>=1)
    Returns ratio in [0,1].
    """
    try:
        size = os.path.getsize(path)
        if size < rec_size:
            return 0.0
        unpack = struct.Struct(fmt).unpack_from
        to_check = min(max_samples, size // rec_size)
        if to_check == 0:
            return 0.0
        hits = 0
        with open(path, "rb") as f:
            data = f.read(min(size, rec_size * to_check))
        for off in range(0, len(data), rec_size):
            if off + rec_size > len(data):
                break
            try:
                key, turn, win, best, plies = unpack(data, off)
            except Exception:
                continue
            valid = True
            if turn not in (0, 1):
                valid = False
            if win not in (0, 1):
                valid = False
            if best != 0xFF:
                fidx = (best >> 4) & 0x0F
                tidx = best & 0x0F
                if not (0 <= fidx <= 15 and 0 <= tidx <= 15):
                    valid = False
            # plies plausibility
            if not (0 <= plies <= 50):
                valid = False
            if win == 1 and plies < 1:
                valid = False
            if valid:
                hits += 1
        return hits / float(to_check)
    except Exception:
        return 0.0


def _detect_solved_record_format_from_path(path: str) -> Tuple[str, int]:
    """
    Auto-detect struct format by trying plausible layouts and scoring field plausibility.
    We compute the record size from struct.calcsize(fmt) to avoid hard-coded mismatches.
    Candidates:
      - 18-byte (MSVC typical): <QBBBxH4x  (8 + 1 + 1 + 1 + 1 pad + 2 + 4 = 18)
      - 17-byte (packed):       <QBBBH4x
      - 16-byte (packed):       <QBBBH3x
      - 25-byte (aligned):      <QBBBxH11x
    """
    fmts: List[str] = [
        # Most plausible for MSVC with 2-byte alignment before H and trailing pad to 24
        "<QBBBxH10x",  # 8 + 1 + 1 + 1 + 1 + 2 + 10 = 24
        # Older packed variant explicitly padding tail to reach 24
        "<QBBBH11x",   # 8 + 1 + 1 + 1 + 2 + 11 = 24 (H at offset 11) — often wrong plies byte order
        # Tight packed
        "<QBBBH3x",    # 16
        "<QBBBH4x",    # 17
        # Alternative: pad before H then larger tail
        "<QBBBxH11x",  # 25
        "<QBBBxH4x",   # 18
    ]
    # Prefer divisible record sizes to avoid partial tail
    fsize = os.path.getsize(path)
    cand = []
    for fmt in fmts:
        try:
            sz = struct.calcsize(fmt)
        except Exception:
            continue
        if sz > 0 and fsize % sz == 0:
            cand.append((fmt, sz))
    probe = cand if cand else [(fmt, struct.calcsize(fmt)) for fmt in fmts]
    best_fmt, best_sz, best_score = None, None, -1.0
    for fmt, rs in probe:
        score = _score_solved_format(path, fmt, rs)
        if score > best_score:
            best_fmt, best_sz, best_score = fmt, rs, score
    if best_fmt is None:
        # Fallback to MSVC-typical 18 bytes
        return "<QBBBxH4x", struct.calcsize("<QBBBxH4x")
    return best_fmt, best_sz


def iter_solved_records(path: str, start: int = 0, limit: Optional[int] = None) -> Iterator[SolvedRecord]:
    fmt, rec_size = _detect_solved_record_format_from_path(path)
    # Ensure rec_size exactly matches the struct format size
    rec_size = struct.calcsize(fmt)
    unpack = struct.Struct(fmt).unpack_from

    with open(path, "rb") as f:
        # Fast skip to start offset
        if start > 0:
            f.seek(start * rec_size)
        remaining = limit if limit is not None else float("inf")

        # Read in reasonable chunks, aligned to record size
        chunk_bytes = max(64 * 1024, rec_size * 1024)
        while remaining > 0:
            to_read = min(chunk_bytes, int(remaining) * rec_size)
            # Round down to multiple of rec_size to avoid trailing partial record
            to_read = (to_read // rec_size) * rec_size
            if to_read <= 0:
                break
            data = f.read(to_read)
            if not data:
                break
            for off in range(0, len(data), rec_size):
                if off + rec_size > len(data):
                    break
                key, turn, win, best, plies = unpack(data, off)
                yield SolvedRecord(
                    key=key,
                    turn=turn,
                    win=win,
                    best=best,
                    plies=plies,
                )
                remaining -= 1
                if remaining == 0:
                    break


# ---------- Binary layout: norm_index.db (optional) ----------

@dataclass
class IndexRecord:
    key: int
    turn: int
    a: int
    b2: int
    b3: int
    b4: int
    x: int
    o: int
    c: int


def _detect_index_record_format(file_size: int) -> Tuple[str, int]:
    """
    IdxRec layout: key(u64), turn(u8), a,b2,b3,b4,x,o,c (u16 each), pad(u8)
    Minimum field bytes: 8 + 1 + 2*7 + 1 = 24
    Try 24-byte and 32-byte alignments.
    """
    candidates: List[Tuple[str, int]] = [
        ("<QBHHHHHHHB", 24),   # tight pack, no extra pad
        ("<QBHHHHHHHB7x", 32), # padded to 32
    ]
    for fmt, sz in candidates:
        if file_size % sz == 0:
            return fmt, sz
    if file_size % 24 == 0:
        return "<QBHHHHHHHB", 24
    # Fallback to 24 as the minimal tight layout
    return "<QBHHHHHHHB", 24


def load_norm_index(path: str) -> Dict[Tuple[int, int], IndexRecord]:
    recs: Dict[Tuple[int, int], IndexRecord] = {}
    size = os.path.getsize(path)
    fmt, rec_size = _detect_index_record_format(size)
    unpack = struct.Struct(fmt).unpack_from
    with open(path, "rb") as f:
        data = f.read()
    for off in range(0, len(data), rec_size):
        if off + rec_size > len(data):
            break
        fields = unpack(data, off)
        # fields: key, turn, a, b2, b3, b4, x, o, c, padOrLast
        key, turn, a, b2, b3, b4, x, o, c, _pad = fields
        recs[(key, turn)] = IndexRecord(key, turn, a, b2, b3, b4, x, o, c)
    return recs


# ---------- Pretty printing ----------

def _card_char(a: int, b2: int, b3: int, b4: int, idx: int) -> str:
    bit = 1 << idx
    if a & bit:
        return "A"
    if b2 & bit:
        return "2"
    if b3 & bit:
        return "3"
    if b4 & bit:
        return "4"
    return "."


def render_overlay_grid(a: int, b2: int, b3: int, b4: int, x: int, o: int, c: int) -> str:
    """
    Overlay precedence: X, O, '#'(collapsed), else card char.
    Returns a multi-line string, 4 rows of 4 space-separated glyphs.
    """
    lines: List[str] = []
    for r in range(4):
        row: List[str] = []
        for cidx in range(4):
            idx = r * 4 + cidx
            bit = 1 << idx
            if x & bit:
                ch = "X"
            elif o & bit:
                ch = "O"
            elif c & bit:
                ch = "#"
            else:
                ch = _card_char(a, b2, b3, b4, idx)
            row.append(ch)
        lines.append(" ".join(row))
    return "\n".join(lines)


def list_raw_keys_for(norm2raw_dir: Optional[str], key: int, turn: int) -> Optional[List[str]]:
    if not norm2raw_dir:
        return None
    fname = f"{key:016x}-{turn}.txt"
    path = os.path.join(norm2raw_dir, fname)
    if not os.path.exists(path):
        return None
    out: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(line)
    return out or None


# ---------- CLI ----------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Read and pretty-print Collapsi solved_norm.db records")
    p.add_argument("--db", default=os.path.join("data", "solved_norm.db"), help="Path to solved_norm.db (default: data/solved_norm.db)")
    p.add_argument("--index", help="Optional path to norm_index.db for grid overlay (should match the same DB origin)")
    p.add_argument("--norm2raw", help="Optional directory of norm2raw/*.txt to list raw keys (e.g., Collapsi/cpp/data/norm2raw)")
    p.add_argument("--start", type=int, default=0, help="Start record index (default: 0)")
    p.add_argument("--limit", type=int, help="Limit number of records to read")
    p.add_argument("--format", choices=["text", "json"], default="text", help="Output format (text/json)")
    p.add_argument("--board", action="store_true", help="If --index provided, print 4x4 overlay grid")
    p.add_argument("--raw-keys", action="store_true", help="If --norm2raw provided, list raw torus-shift keys")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"error: solved db not found: {args.db}", file=sys.stderr)
        return 2

    idx_map: Dict[Tuple[int, int], IndexRecord] = {}
    if args.index:
        if not os.path.exists(args.index):
            print(f"warning: index not found: {args.index} (board overlay will be unavailable)", file=sys.stderr)
        else:
            idx_map = load_norm_index(args.index)

    # Streaming read
    if args.format == "json":
        # JSON array streamed as list with one object per record
        first = True
        sys.stdout.write("[")
        for rec in iter_solved_records(args.db, start=args.start, limit=args.limit):
            obj = {
                "key": f"{rec.key:016x}",
                "turn": rec.turn,
                "win": int(rec.win),
                "plies": int(rec.plies),
            }
            mv = decode_move(rec.best)
            if mv is not None:
                rf, cf, rt, ct = mv
                obj["best"] = {
                    "encoded": rec.best,
                    "from": {"idx": (rf * 4 + cf), "r": rf, "c": cf},
                    "to": {"idx": (rt * 4 + ct), "r": rt, "c": ct},
                }
            else:
                obj["best"] = None

            if idx_map:
                idx = idx_map.get((rec.key, rec.turn))
                if idx:
                    obj["grid"] = {
                        "a": idx.a, "b2": idx.b2, "b3": idx.b3, "b4": idx.b4,
                        "x": idx.x, "o": idx.o, "c": idx.c,
                    }

            if args.norm2raw and args.raw_keys:
                raw = list_raw_keys_for(args.norm2raw, rec.key, rec.turn)
                if raw:
                    obj["raw_keys"] = raw

            if not first:
                sys.stdout.write(",")
            first = False
            sys.stdout.write(json.dumps(obj))
        sys.stdout.write("]\n")
        return 0

    # text format
    count = 0
    for rec in iter_solved_records(args.db, start=args.start, limit=args.limit):
        print(f"normalized_key: {human_key(rec.key, rec.turn)}")
        print(f"  win={int(rec.win)} plies={int(rec.plies)}")
        mv = decode_move(rec.best)
        if mv is None:
            print(f"  best: none (0xFF)")
        else:
            rf, cf, rt, ct = mv
            print(f"  best: {rec.best} from=({rf},{cf}) to=({rt},{ct})")

        if args.index and args.board and idx_map:
            idx = idx_map.get((rec.key, rec.turn))
            if idx:
                print("  Board (normalized, overlay):")
                grid = render_overlay_grid(idx.a, idx.b2, idx.b3, idx.b4, idx.x, idx.o, idx.c)
                print("\n".join("    " + line for line in grid.splitlines()))
            else:
                print("  Board: (missing in index)")

        if args.norm2raw and args.raw_keys:
            raw = list_raw_keys_for(args.norm2raw, rec.key, rec.turn)
            if raw:
                print("  raw torus keys:")
                for line in raw:
                    print(f"    {line}")

        print()
        count += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())