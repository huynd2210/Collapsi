from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .board import Board, Coord


@dataclass(frozen=True)
class GameState:
    """Represents the dynamic state of the game, including player positions and collapsed cards."""
    board: Board
    collapsed: Tuple[Coord, ...]  # immutable, sorted for consistent hashing
    p1: Coord
    p2: Coord
    turn: int  # 1 or 2

    def is_collapsed(self, coord: Coord) -> bool:
        return coord in set(self.collapsed)

    def other_player(self) -> int:
        return 2 if self.turn == 1 else 1

    def player_pos(self, player: int) -> Coord:
        return self.p1 if player == 1 else self.p2

    def with_turn(self, next_turn: int) -> 'GameState':
        return GameState(self.board, self.collapsed, self.p1, self.p2, next_turn)