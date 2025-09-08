from __future__ import annotations

from typing import Optional

from .state import GameState
from .board import Coord
from .solver_cli import solve_with_cache_impl


def choose_ai_side_for_board(board, p1: Coord, p2: Coord, db_path: str) -> int:
    """Determines which side the AI should play, based on which player has a cached win."""
    state_p1 = GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=1)
    res_p1 = solve_with_cache_impl(state_p1, db_path)
    if res_p1.win:
        return 1
    state_p2 = GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=2)
    res_p2 = solve_with_cache_impl(state_p2, db_path)
    return 2 if res_p2.win else 1  # Default to Player 1 if neither side has a cached win.


def ai_pick_move(state: GameState, db_path: str) -> Optional[Coord]:
    """Picks the best move for the AI by solving the current game state."""
    res = solve_with_cache_impl(state, db_path)
    return res.best_move if res.win else None


def aostar_solve(state: GameState, *args, **kwargs):
    """Deprecated shim preserved for compatibility."""
    return solve_with_cache_impl(state, db_path=kwargs.get('db_path', 'collapsi.db'))