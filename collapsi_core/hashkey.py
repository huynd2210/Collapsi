from __future__ import annotations

from typing import Tuple

from .board import Board, Card, Coord
from .state import GameState
from .normalize import _normalize_for_torus, _shift_coord, _shift_grid_str


def _state_bitboards(state: GameState) -> Tuple[int, int, int, int, int, int, int, int]:
    """Return (a, b2, b3, b4, x, o, collapsed, turn) as integers for hashing/storage."""
    w = state.board.width
    h = state.board.height
    if w != 4 or h != 4:
        raise ValueError('Only 4x4 supported for bitboard hashing')
    a = b2 = b3 = b4 = 0
    for r in range(4):
        for c in range(4):
            idx = r * 4 + c
            card = state.board.at(r, c)
            if card in ('A', 'J'):
                a |= (1 << idx)
            elif card == '2':
                b2 |= (1 << idx)
            elif card == '3':
                b3 |= (1 << idx)
            elif card == '4':
                b4 |= (1 << idx)
    x = (1 << (state.p1[0] * 4 + state.p1[1]))
    o = (1 << (state.p2[0] * 4 + state.p2[1]))
    c = 0
    for (rr, cc) in state.collapsed:
        c |= (1 << (rr * 4 + cc))
    turn = 0 if state.turn == 1 else 1
    return a, b2, b3, b4, x, o, c, turn


def _pair64(left: int, right: int) -> int:
    if left >= right:
        return (left * left) + left + right
    else:
        return left + (right * right)


def _mix64(value: int) -> int:
    value = (value + 0x9e3779b97f4a7c15) & 0xFFFFFFFFFFFFFFFF
    value ^= (value >> 30)
    value = (value * 0xbf58476d1ce4e5b9) & 0xFFFFFFFFFFFFFFFF
    value ^= (value >> 27)
    value = (value * 0x94d049bb133111eb) & 0xFFFFFFFFFFFFFFFF
    value ^= (value >> 31)
    return value & 0xFFFFFFFFFFFFFFFF


def _hash_state64(vals: Tuple[int, ...]) -> int:
    h = 0
    for v in vals:
        h = _pair64(h, v & 0xFFFFFFFFFFFFFFFF) & 0xFFFFFFFFFFFFFFFF
    return _mix64(h)


def _raw_state_key(state: GameState) -> str:
    """64-bit key for the raw (unnormalized) state using bitboards and turn."""
    a, b2, b3, b4, x, o, c, turn = _state_bitboards(state)
    key64 = _hash_state64((a, b2, b3, b4, x, o, c, turn))
    return f"{key64:016x}|{turn}"


def _state_key(state: GameState) -> str:
    """Generates a compact key: 64-bit hash from bitboards using Szudzik+SplitMix64.
    Omits width/height (assume 4x4), and stores only the hash as hex + turn.
    Uses torus normalization by shifting so X at (0,0) before hashing.
    """
    # shift so X at (0,0)
    w, h = state.board.width, state.board.height
    grid_str, norm_p1, norm_p2, norm_collapsed, dr, dc = _normalize_for_torus(state)
    norm_board = Board(width=w, height=h, grid=tuple(grid_str))
    norm_state = GameState(board=norm_board, collapsed=norm_collapsed, p1=norm_p1, p2=norm_p2, turn=state.turn)
    a, b2, b3, b4, x, o, c, turn = _state_bitboards(norm_state)
    key64 = _hash_state64((a, b2, b3, b4, x, o, c, turn))
    return f"{key64:016x}|{turn}"