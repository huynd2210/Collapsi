#!/usr/bin/env python3
"""
Reproduce and check monotonic plies along a concrete line.

- Uses the native CLI via game.solve_moves_cpp/solve_with_cache.
- Prints, for each step:
  * Root plies (from current state)
  * Per-move "m -> (W/L, plies)"
  * If a scripted move is applied, compares the predicted plies for that move
    with the observed plies after one or two plies have elapsed.

Expected monotonicity (for a winning line):
- If the solver says move M has "plies = P" for the current side:
  After applying M (1 ply) and the opponent's delaying reply (1 ply),
  the new state's root plies (same side again) should be (P - 2).
"""

from __future__ import annotations

from typing import List, Tuple, Optional
import os
import sys

# Ensure we can import local game glue when running from repo root
try:
    from game import (
        Board,
        GameState,
        legal_moves,
        apply_move,
        solve_with_cache,
        solve_moves_cpp,
    )
except ImportError:
    # Add Collapsi/ to sys.path when running from repo root
    sys.path.append(os.path.join(os.getcwd(), "Collapsi"))
    from game import (
        Board,
        GameState,
        legal_moves,
        apply_move,
        solve_with_cache,
        solve_moves_cpp,
    )

Coord = Tuple[int, int]

def parse_overlay(rows: List[str], underlying_xo_card: str = "J") -> Tuple[Board, Coord, Coord]:
    """
    Parse overlay rows (4 strings of length 4) where 'X' and 'O' mark player pieces.
    The underlying card at X/O cells is treated as 'J' (A-like = step 1).
    Returns (Board, p1, p2).
    """
    assert len(rows) == 4 and all(len(r) == 4 for r in rows), "Provide exactly 4 rows of length 4"
    grid: List[str] = []
    p1: Optional[Coord] = None
    p2: Optional[Coord] = None
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch == "X":
                if p1 is not None:
                    raise ValueError("Multiple X found")
                p1 = (r, c)
                grid.append(underlying_xo_card)
            elif ch == "O":
                if p2 is not None:
                    raise ValueError("Multiple O found")
                p2 = (r, c)
                grid.append(underlying_xo_card)
            else:
                grid.append(ch)
    if p1 is None or p2 is None:
        raise ValueError("Missing X or O in overlay")
    return Board(width=4, height=4, grid=tuple(grid)), p1, p2

def per_move_map(state: GameState):
    items = solve_moves_cpp(state)
    mp = {}
    for it in items:
        mv = tuple(it["move"])
        mp[mv] = {"win": bool(it["win"]), "plies": it.get("plies")}
    return mp, items

def fmt_moves(items):
    parts = []
    for it in items:
        mv = tuple(it["move"])
        parts.append(f"{mv}:{'W' if it['win'] else 'L'}:{it.get('plies')}")
    return "[" + ", ".join(parts) + "]"

def run_line(rows: List[str], line_moves: List[Tuple[Coord, Optional[Coord]]], title: str) -> None:
    db_path = "collapsi.db"
    board, p1, p2 = parse_overlay(rows, underlying_xo_card="J")
    state = GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=1)  # X starts
    print(f"=== {title} ===")
    print("Overlay:")
    print("\n".join(rows))
    print("\nStart:")
    print(board.pretty(p1, p2, set()))
    step = 0
    predicted_after_two: Optional[int] = None

    for x_move, o_move in line_moves:
        step += 1
        print(f"\nStep {step} (X to move)")
        root = solve_with_cache(state, db_path)
        print(f"Root says: win={root.win} plies={root.plies} best={root.best_move}")
        mp, items = per_move_map(state)
        print("Per-move:", fmt_moves(items))
        if x_move not in legal_moves(state):
            print(f"X scripted move {x_move} is ILLEGAL here; legal={legal_moves(state)}")
            return
        # Predict after two plies if we have a metric for this move
        sel = mp.get(x_move)
        if sel and isinstance(sel.get("plies"), int):
            predicted_after_two = int(sel["plies"]) - 2
        else:
            predicted_after_two = None
        state = apply_move(state, x_move)
        print(f"X plays {x_move}")
        print(state.board.pretty(state.p1, state.p2, set(state.collapsed)))

        # Opponent reply scripted?
        if o_move is not None:
            if o_move not in legal_moves(state):
                print(f"O scripted move {o_move} is ILLEGAL here; legal={legal_moves(state)}")
                return
            state = apply_move(state, o_move)
            print(f"O plays {o_move}")
            print(state.board.pretty(state.p1, state.p2, set(state.collapsed)))
            # Now it's X to move again; check new root plies vs predicted_after_two
            nxt = solve_with_cache(state, db_path)
            print(f"After two plies, root says: win={nxt.win} plies={nxt.plies} best={nxt.best_move}")
            if predicted_after_two is not None and isinstance(nxt.plies, int):
                delta = nxt.plies - predicted_after_two
                status = "OK" if nxt.plies == predicted_after_two else f"MISMATCH (expected {predicted_after_two}, got {nxt.plies}, delta={delta})"
                print(f"Monotonic check: {status}")
        else:
            # No scripted O move; just show O's options and predicted worst reply
            mp2, items2 = per_move_map(state)
            print("O per-move:", fmt_moves(items2))

def main() -> int:
    # User-reported board
    rows = [
        "24A2",
        "X33A",
        "2AO2",
        "3A34",
    ]
    # Attempt 1: Interpret the final history as:
    # 1: X->(0,0), O->(2,3)
    # 2: X->(0,2), O->(2,1)
    # 3: X->(0,1), O->(1,1)
    # 4: X->(3,2), O->None (unspecified)
    seq1 = [
        ((0, 0), (2, 3)),
        ((0, 2), (2, 1)),
        ((0, 1), (1, 1)),
        ((3, 2), None),
    ]

    # Attempt 2: Alternative (if the narrative "I play (2,1) then AI (0,1)" meant X moved (2,1) at #2)
    # 1: X->(0,0), O->(2,3)
    # 2: X->(2,1), O->(0,1)
    # 3: X->(1,1), O->(3,2)
    seq2 = [
        ((0, 0), (2, 3)),
        ((2, 1), (0, 1)),
        ((1, 1), (3, 2)),
    ]

    print("\n================ Variant 1 ================\n")
    run_line(rows, seq1, "Variant 1")
    print("\n================ Variant 2 ================\n")
    run_line(rows, seq2, "Variant 2")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())