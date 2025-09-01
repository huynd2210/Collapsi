#!/usr/bin/env python3
"""
Quick inspector to test candidate struct formats against a solved_norm.db file.
Prints the first K records for each candidate format so we can see which one yields plausible fields.
"""
import os, struct, sys

PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "test_solved_norm.db")
K = int(sys.argv[2]) if len(sys.argv) > 2 else 5

fmts = [
    ("<QBBBH3x", "16B  = <QBBBH3x"),
    ("<QBBBH4x", "17B  = <QBBBH4x"),
    ("<QBBBxH4x", "18B* = <QBBBxH4x  (MSVC typical: pad before H + 4x tail)"),
    ("<QBBBH11x", "24B  = <QBBBH11x"),
    ("<QBBBxH11x", "25B  = <QBBBxH11x"),
]

size = os.path.getsize(PATH)
print(f"File: {PATH} size={size}")
print("Format sizes & modulo of file size:")
for fmt, label in fmts:
    try:
        sz = struct.calcsize(fmt)
        print(f"  {label} -> {sz} bytes;  size % sz = {size % sz}")
    except Exception as e:
        print(f"  {label} -> error: {e}")

with open(PATH, "rb") as f:
    buf = f.read(1024)

def safe_unpack(fmt, data, off):
    try:
        return struct.Struct(fmt).unpack_from(data, off)
    except Exception as e:
        return f"ERR: {e}"

print("\nFirst records per format:")
for fmt, label in fmts:
    try:
        sz = struct.calcsize(fmt)
    except Exception:
        continue
    print(f"\n-- {label} --")
    off = 0
    for i in range(K):
        if off + sz > len(buf):
            print("  (not enough bytes in initial buffer)")
            break
        out = safe_unpack(fmt, buf, off)
        if isinstance(out, tuple):
            key, turn, win, best, plies = out[:5]
            print(f"  rec[{i}] key={key:016x} turn={turn} win={win} best={best} plies={plies}")
        else:
            print(f"  rec[{i}] {out}")
        off += sz