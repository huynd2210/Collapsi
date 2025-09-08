from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple, Set, List, Optional

Card = str  # 'J', 'A', '2', '3', '4'
Coord = Tuple[int, int]


@dataclass(frozen=True)
class Board:
    """Represents the static game board, including its dimensions and the grid of cards."""
    width: int
    height: int
    grid: Tuple[Card, ...]  # row-major, length == width * height

    def index(self, r: int, c: int) -> int:
        """Calculates the 1D index for a given row and column."""
        return r * self.width + c

    def at(self, r: int, c: int) -> Card:
        """Gets the card at a given row and column with wrap-around logic."""
        return self.grid[self.index(r % self.height, c % self.width)]

    def coords(self) -> Iterable[Coord]:
        """Iterates over all coordinates on the board."""
        for r in range(self.height):
            for c in range(self.width):
                yield (r, c)

    def pretty(
        self,
        p1: Optional[Coord] = None,
        p2: Optional[Coord] = None,
        collapsed: Optional[Set[Coord]] = None,
    ) -> str:
        """Generates a human-readable string representation of the board state."""
        lines: List[str] = []
        cset = collapsed or set()
        for r in range(self.height):
            row: List[str] = []
            for c in range(self.width):
                cell = self.at(r, c)
                if (r, c) in cset:
                    row.append("·")
                elif p1 == (r, c) and p2 == (r, c):
                    row.append("*")
                elif p1 == (r, c):
                    row.append("X")
                elif p2 == (r, c):
                    row.append("O")
                else:
                    row.append(cell)
            lines.append(" ".join(row))
        return "\n".join(lines)