from __future__ import annotations

import os
import struct
import math
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple


@dataclass
class SolvedRecord:
    key: int
    turn: int  # 0 X, 1 O
    win: int   # 0/1
    best: int  # uint8, 0xFF means none
    plies: int # uint16

def is_sqlite_file(path: str) -> bool:
    """
    Quick check: return True if file starts with "SQLite format 3\\0" header.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(16)
        return head.startswith(b"SQLite format 3\x00")
    except Exception:
        return False

def _score_solved_format(path: str, fmt: str, rec_size: int, max_samples: int = 512) -> float:
    """
    Heuristic scoring for format detection.
    We consider only non-zero keys to avoid zero-padding bias.
    A record is plausible when:
      - key != 0
      - turn in {0,1}
      - win in {0,1}
      - best is 0xFF or encodes from/to nibbles in [0,15]
      - plies in [0,50] and (win==1 => plies>=1)
    Returns ratio in [0,1] computed over non-zero samples; if none, returns 0.
    """
    try:
        size = os.path.getsize(path)
        if size < rec_size:
            return 0.0
        unpack = struct.Struct(fmt).unpack_from
        to_check = min(max_samples, size // rec_size)
        if to_check == 0:
            return 0.0
        hits_nonzero = 0
        samples_nonzero = 0
        with open(path, "rb") as f:
            data = f.read(min(size, rec_size * to_check))
        for off in range(0, len(data), rec_size):
            if off + rec_size > len(data):
                break
            try:
                key, turn, win, best, plies = unpack(data, off)
            except Exception:
                continue
            if int(key) == 0:
                continue  # ignore zero-key padding when scoring
            samples_nonzero += 1
            valid = True
            if turn not in (0, 1): valid = False
            if win not in (0, 1): valid = False
            if best != 0xFF:
                fidx = (best >> 4) & 0x0F
                tidx = best & 0x0F
                if not (0 <= fidx <= 15 and 0 <= tidx <= 15):
                    valid = False
            if not (0 <= plies <= 50): valid = False
            if win == 1 and plies < 1: valid = False
            if valid:
                hits_nonzero += 1
        if samples_nonzero == 0:
            return 0.0
        return hits_nonzero / float(samples_nonzero)
    except Exception:
        return 0.0


def detect_record_format(path: str) -> Tuple[str, int]:
    """
    Robust detection for solved_norm*.db binary records.

    Only consider record sizes that evenly divide the file size to avoid misalignment.
    Prefer canonical 16- or 24-byte layouts; fall back to 16-byte if undecidable.
    """
    fsize = os.path.getsize(path)
    if fsize <= 0:
        return "<QBBBH3x", struct.calcsize("<QBBBH3x")

    candidates: List[str] = [
        "<QBBBH3x",    # 16-byte packed: key(u64),turn(u8),win(u8),best(u8),plies(u16),pad(3)
        "<QBBBxH10x",  # 24-byte: key(u64),turn(u8),win(u8),best(u8),pad(u8),plies(u16),pad(10)
        "<QBBBH11x",   # 24-byte alt
    ]

    # Strict: only sizes that divide file size
    probe: List[Tuple[str, int]] = []
    for fmt in candidates:
        try:
            sz = struct.calcsize(fmt)
        except Exception:
            continue
        if sz > 0 and (fsize % sz == 0):
            probe.append((fmt, sz))

    # If none divide evenly, try both 16 and 24 and let plausibility scoring decide
    if not probe:
        for fmt in candidates:
            try:
                sz = struct.calcsize(fmt)
                if sz > 0:
                    probe.append((fmt, sz))
            except Exception:
                continue

    best_fmt, best_sz, best_score = None, None, -1.0
    for fmt, rs in probe:
        score = _score_solved_format(path, fmt, rs)
        if score > best_score:
            best_fmt, best_sz, best_score = fmt, rs, score

    if best_fmt is None:
        return "<QBBBH3x", struct.calcsize("<QBBBH3x")
    return best_fmt, best_sz


def iter_records(path: str, start: int = 0, limit: Optional[int] = None) -> Iterator[SolvedRecord]:
    fmt, rec_size = detect_record_format(path)
    rec_size = struct.calcsize(fmt)
    unpack = struct.Struct(fmt).unpack_from
    with open(path, "rb") as f:
        if start > 0:
            f.seek(start * rec_size)
        if limit is None:
            remaining: int = 1 << 60
        else:
            remaining: int = max(0, int(limit))
        chunk_bytes = max(64 * 1024, rec_size * 1024)
        while remaining > 0:
            # Read by fixed chunk size; remaining counts YIELDED records, not raw records
            to_read = chunk_bytes
            data = f.read(to_read)
            if not data:
                break
            for off in range(0, len(data), rec_size):
                if off + rec_size > len(data):
                    break
                try:
                    key, turn, win, best, plies = unpack(data, off)
                except Exception:
                    continue
                # Filter out invalid/garbage records
                if int(key) == 0:
                    continue
                iturn = int(turn)
                iwin = int(win)
                iplies = int(plies)
                ibest = int(best)
                if iturn not in (0, 1):
                    continue
                if iwin not in (0, 1):
                    continue
                if not (0 <= iplies <= 50):
                    continue
                if iwin == 1 and iplies < 1:
                    continue
                if ibest != 0xFF:
                    fidx = (ibest >> 4) & 0x0F
                    tidx = ibest & 0x0F
                    if not (0 <= fidx <= 15 and 0 <= tidx <= 15):
                        continue
                yield SolvedRecord(
                    key=int(key),
                    turn=iturn,
                    win=iwin,
                    best=ibest,
                    plies=iplies,
                )
                remaining -= 1
                if remaining == 0:
                    break


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


def _detect_index_format(file_size: int) -> Tuple[str, int]:
    """
    IdxRec layout: key(u64), turn(u8), a,b2,b3,b4,x,o,c (u16 each), pad(u8)
    Minimum field bytes: 8 + 1 + 2*7 + 1 = 24
    Try 24-byte and 32-byte alignments.
    """
    candidates: List[Tuple[str, int]] = [
        ("<QBHHHHHHHB", 24),    # tight pack
        ("<QBHHHHHHHB7x", 32),  # padded to 32
    ]
    for fmt, sz in candidates:
        if file_size % sz == 0:
            return fmt, sz
    if file_size % 24 == 0:
        return "<QBHHHHHHHB", 24
    return "<QBHHHHHHHB", 24


def load_norm_index(path: str) -> Dict[Tuple[int, int], IndexRecord]:
    recs: Dict[Tuple[int, int], IndexRecord] = {}
    size = os.path.getsize(path)
    fmt, rec_size = _detect_index_format(size)
    unpack = struct.Struct(fmt).unpack_from
    with open(path, "rb") as f:
        data = f.read()
    for off in range(0, len(data), rec_size):
        if off + rec_size > len(data):
            break
        fields = unpack(data, off)
        key, turn, a, b2, b3, b4, x, o, c, _pad = fields
        recs[(int(key), int(turn))] = IndexRecord(int(key), int(turn), int(a), int(b2), int(b3), int(b4), int(x), int(o), int(c))
    return recs