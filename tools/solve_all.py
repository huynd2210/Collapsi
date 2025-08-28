from __future__ import annotations

import argparse
import itertools
import os
import sys
import time
from typing import Iterable, List, Sequence, Tuple

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from game import Board, GameState, _state_key  # type: ignore
from game import normalize_for_torus_view, _raw_state_key  # type: ignore


Coord = Tuple[int, int]


def idx_to_rc(idx: int, w: int) -> Coord:
    return (idx // w, idx % w)


def build_grid_from_positions(j2: int, a_pos: Sequence[int], two_pos: Sequence[int], three_pos: Sequence[int], w: int = 4, h: int = 4) -> Tuple[Tuple[str, ...], Coord, Coord]:
    total = w * h
    grid = [''] * total
    # Place Js
    grid[0] = 'J'
    grid[j2] = 'J'
    # Fill others
    for i in a_pos:
        grid[i] = 'A'
    for i in two_pos:
        grid[i] = '2'
    for i in three_pos:
        grid[i] = '3'
    # Remaining are '4'
    for i in range(total):
        if grid[i] == '':
            grid[i] = '4'
    return tuple(grid), idx_to_rc(0, w), idx_to_rc(j2, w)


def enumerate_canonical_grids() -> Iterable[Tuple[Tuple[str, ...], Coord, Coord]]:
    """Enumerate 4x4 grids with composition 2xJ, 4xA, 4x2, 4x3, 2x4, fixing one J at index 0.
    This removes 16× torus translations on average by fixing X at (0,0)."""
    all_idx = list(range(16))
    for j2 in range(1, 16):
        rem1 = [i for i in all_idx if i not in (0, j2)]
        for a_pos in itertools.combinations(rem1, 4):
            rem2 = [i for i in rem1 if i not in a_pos]
            for two_pos in itertools.combinations(rem2, 4):
                rem3 = [i for i in rem2 if i not in two_pos]
                for three_pos in itertools.combinations(rem3, 4):
                    yield build_grid_from_positions(j2, a_pos, two_pos, three_pos)


def process(args: argparse.Namespace) -> None:
    w = 4
    h = 4
    db = args.db
    stride = max(1, int(args.stride))
    offset = max(0, int(args.offset))
    max_count = int(args.limit) if args.limit is not None else None
    start_time = time.time()
    processed = 0
    solved = 0
    skipped = 0

    j2_values = list(range(1, 16))
    j2_values = [j2 for i, j2 in enumerate(j2_values) if (i % stride) == offset]

    for j2 in j2_values:
        rem1 = [i for i in range(16) if i not in (0, j2)]
        for a_pos in itertools.combinations(rem1, 4):
            rem2 = [i for i in rem1 if i not in a_pos]
            for two_pos in itertools.combinations(rem2, 4):
                rem3 = [i for i in rem2 if i not in two_pos]
                for three_pos in itertools.combinations(rem3, 4):
                    grid, p1, p2 = build_grid_from_positions(j2, a_pos, two_pos, three_pos, w, h)
                    board = Board(width=w, height=h, grid=grid)
                    # Build raw (unnormalized) states for both turns
                    raw_states = [
                        GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=1),
                        GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=2),
                    ]
                    # Compute normalized key for mapping (use turn=1 canonical as representative)
                    norm_board, np1, np2, ncol, dr, dc = normalize_for_torus_view(raw_states[0])
                    norm_state = GameState(board=norm_board, collapsed=ncol, p1=np1, p2=np2, turn=1)
                    norm_key = _state_key(norm_state)
                    # Only generate mapping files now (no solving)
                    # Prepare output dirs under project data/
                    base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
                    norm_dir = os.path.join(base, 'norm2raw')
                    raw_dir = os.path.join(base, 'raw2norm')
                    os.makedirs(norm_dir, exist_ok=True)
                    os.makedirs(raw_dir, exist_ok=True)
                    # Sanitize filenames (Windows: '|' is invalid)
                    norm_fname = norm_key.replace('|', '-') + '.txt'
                    norm_path = os.path.join(norm_dir, norm_fname)
                    for rs in raw_states:
                        raw_key = _raw_state_key(rs)
                        raw_fname = raw_key.replace('|', '-') + '.txt'
                        raw_path = os.path.join(raw_dir, raw_fname)
                        # Append to norm2raw list
                        with open(norm_path, 'a', encoding='utf-8') as f:
                            f.write(raw_key + '\n')
                        # Write/overwrite raw2norm mapping (single line)
                        with open(raw_path, 'w', encoding='utf-8') as f:
                            f.write(norm_key)
                    processed += 1
                    if max_count is not None and processed >= max_count:
                        break
                if max_count is not None and processed >= max_count:
                    break
            if max_count is not None and processed >= max_count:
                break
        if max_count is not None and processed >= max_count:
            break

    elapsed = time.time() - start_time
    print(f"Processed={processed} solved={solved} skipped={skipped} elapsed_sec={elapsed:.1f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Exhaustively solve 4x4 Collapsi boards (canonicalized by torus shift)")
    parser.add_argument('--db', default='collapsi.db', help='SQLite DB file path')
    parser.add_argument('--stride', type=int, default=1, help='Shard stride for parallel runs (default 1)')
    parser.add_argument('--offset', type=int, default=0, help='Shard offset [0..stride-1] for parallel runs')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of processed grids (for testing)')
    args = parser.parse_args()
    process(args)


if __name__ == '__main__':
    main()


