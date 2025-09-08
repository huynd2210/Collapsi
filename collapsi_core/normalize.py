from __future__ import annotations

from typing import List, Tuple

from .board import Board, Card, Coord
from .state import GameState


def _shift_coord(c: Coord, dr: int, dc: int, w: int, h: int) -> Coord:
    r, c0 = c
    return ((r + dr) % h, (c0 + dc) % w)


def _shift_grid_str(grid: Tuple[Card, ...], w: int, h: int, dr: int, dc: int) -> str:
    # Build shifted grid string row-major
    s: List[str] = []
    for r in range(h):
        for c in range(w):
            sr = (r - dr) % h
            sc = (c - dc) % w
            s.append(grid[sr * w + sc])
    return ''.join(s)


def _normalize_for_torus(state: GameState) -> Tuple[str, Coord, Coord, Tuple[Coord, ...], int, int]:
    """Compute normalized key components by shifting so that X is at (0,0). Returns:
    (normalized_grid_str, norm_p1, norm_p2, norm_collapsed, dr, dc)."""
    w, h = state.board.width, state.board.height
    x_r, x_c = state.p1
    dr = (-x_r) % h
    dc = (-x_c) % w
    grid_str = _shift_grid_str(state.board.grid, w, h, dr, dc)
    norm_p1 = (0, 0)
    norm_p2 = _shift_coord(state.p2, dr, dc, w, h)
    norm_collapsed = tuple(sorted((_shift_coord(c, dr, dc, w, h) for c in state.collapsed)))
    return grid_str, norm_p1, norm_p2, norm_collapsed, dr, dc


def normalize_for_torus_view(state: GameState) -> Tuple[Board, Coord, Coord, Tuple[Coord, ...], int, int]:
    """Build a normalized GameState view (for UI), shifting so X ends at (0,0). Returns
    (norm_board, norm_p1, norm_p2, norm_collapsed, dr, dc)."""
    w, h = state.board.width, state.board.height
    grid_str, norm_p1, norm_p2, norm_collapsed, dr, dc = _normalize_for_torus(state)
    norm_board = Board(width=w, height=h, grid=tuple(grid_str))
    return norm_board, norm_p1, norm_p2, norm_collapsed, dr, dc