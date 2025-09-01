#!/usr/bin/env python3
"""
Reproduce/diagnose the reported AI defeat on a specific 4x4 board and move history.

- Parses a 4x4 overlay board where 'X' and 'O' are player overlays on top of card letters.
- Assumes the underlying cards at X/O are 'J' (treated as 'A' for steps), per docs:
  "A includes J positions" and J/A both step=1.
- Replays the provided move sequence, checks legality, and queries the C++ solver at each ply.
- Prints anomalies when solver claims a win but the scripted line appears to refute it.

Note: This script uses the existing Flask/game glue functions and the C++ CLI if present.
If the CLI executable is not found, it still validates rules/legality but cannot validate solver outcomes.

Related code paths:
- C++ solver recursion: [solver.solve_rec()](Collapsi/cpp/src/solver.cpp:27)
- Destination enumeration: [bitboard.enumerate_destinations()](Collapsi/cpp/src/bitboard.cpp:62)
- Flask AI endpoint logic: [app.api_ai()](Collapsi/app.py:295)

Usage:
  python Collapsi/tools/repro_ai_bug.py
"""

from __future__ import annotations

from typing import List, Tuple, Optional, Iterable
import sys
import os

# Use the game glue to access model + solver/CLI
try:
    from game import (
        Board,
        GameState,
        legal_moves,
        apply_move,
        solve_with_cache,
        solve_moves_cpp,
        _state_to_cpp_arg,
    )
except ImportError:
    # Allow running from repo root by adding Collapsi/ to sys.path
    sys.path.append(os.path.join(os.getcwd(), "Collapsi"))
    from game import (
        Board,
        GameState,
        legal_moves,
        apply_move,
        solve_with_cache,
        solve_moves_cpp,
        _state_to_cpp_arg,
    )

Coord = Tuple[int, int]


def parse_overlay(rows: List[str], underlying_xo_card: str = "J") -> Tuple[Board, Coord, Coord]:
    """
    Parse 4 overlay rows (length 4 each) into:
      - Board with card letters (X and O replaced by underlying_xo_card)
      - p1 (X) coordinate
      - p2 (O) coordinate
    """
    assert len(rows) == 4 and all(len(r) == 4 for r in rows), "Must provide 4 rows of length 4"
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


def pretty_moves(moves: Iterable[Coord]) -> str:
    return "[" + ", ".join(f"({r},{c})" for (r, c) in moves) + "]"


def check_and_apply(state: GameState, dest: Coord, who: str, db_path: str) -> GameState:
    """
    Prints solver status for current state (if CLI available),
    verifies legality of 'dest', then applies it.
    """
    # Query solver before the move (if CLI exists)
    res = solve_with_cache(state, db_path)
    if res.plies is not None:
        print(f"  Solver says: win={res.win} plies={res.plies} best={res.best_move}")
    else:
        print(f"  Solver says: win={res.win} plies=None best={res.best_move}")

    # Per-move metrics (if available)
    detailed = solve_moves_cpp(state)
    if detailed:
        # Normalize to compact display
        md = ", ".join(f"{tuple(m['move'])}:{'W' if m['win'] else 'L'}:{m['plies'] if m['plies'] is not None else '-'}" for m in detailed)
        print(f"  Per-move: {md}")

    # Legality check
    legal = legal_moves(state)
    if dest not in legal:
        print(f"  ILLEGAL {who} move {dest}! Legal were: {pretty_moves(legal)}")
        return state  # return unchanged to continue inspection

    # Apply
    nstate = apply_move(state, dest)
    return nstate


def main() -> int:
    # Reported board:
    #   AX22
    #   2333
    #   AO43
    #   A42A
    #
    # We interpret underlying cards at X and O as 'J'.
    rows = [
        "AX22",
        "2333",
        "AO43",
        "A42A",
    ]
    board, p1, p2 = parse_overlay(rows, underlying_xo_card="J")
    state = GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=1)  # X to move first

    # Provided move history (pairs of (X_dest, O_dest) per ply number)
    move_pairs: List[Tuple[Coord, Coord]] = [
        ((0, 0), (2, 2)),
        ((0, 3), (3, 1)),
        ((1, 0), (1, 1)),
        ((1, 2), (2, 3)),
        ((2, 0), (3, 3)),
        ((3, 0), (3, 2)),
    ]

    db_path = "collapsi.db"

    print("Initial board (overlay):")
    print("\n".join(rows))
    print("\nCard grid used by solver (X/O cells treated as 'J'):")
    print(board.pretty(p1=None, p2=None, collapsed=set()))
    print(f"\nStart: X at {state.p1}, O at {state.p2}, turn={state.turn} (X=1, O=2)")
    try:
        enc = _state_to_cpp_arg(state)
        print(f"Encoded --state for CLI: {enc}\n")
    except Exception:
        print()

    # Replay moves
    for i, (x_move, o_move) in enumerate(move_pairs, start=1):
        print(f"Move {i}.X to {x_move}")
        state = check_and_apply(state, x_move, who="X", db_path=db_path)
        print(board.pretty(state.p1, state.p2, set(state.collapsed)))
        print()

        print(f"Move {i}.O to {o_move}")
        state = check_and_apply(state, o_move, who="O", db_path=db_path)
        print(board.pretty(state.p1, state.p2, set(state.collapsed)))
        print()

    # After last O move, check terminal
    lm = legal_moves(state)
    print(f"After last move, legal moves for side-to-move (turn={state.turn}): {pretty_moves(lm)}")
    if not lm:
        # If the current player has no legal moves, the previous mover wins
        prev = 1 if state.turn == 2 else 2
        print(f"Terminal: Player {prev} wins (opponent has no legal moves).")

    # Also, query solver final stance on the final position (if CLI exists)
    res_final = solve_with_cache(state, db_path)
    print(f"Final position solver says: win={res_final.win} plies={res_final.plies} best={res_final.best_move}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())