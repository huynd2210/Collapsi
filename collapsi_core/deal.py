from __future__ import annotations

import random
from typing import List, Optional, Tuple

from .board import Board, Card, Coord


def deal_board_4x4(seed: Optional[int] = None) -> Tuple[Board, Coord, Coord]:
    """Creates and deals a 4x4 board with a standard deck of 16 cards."""
    rng = random.Random(seed)
    # Deck composition for a 4x4 board.
    deck: List[Card] = ['J', 'J'] + ['A'] * 4 + ['2'] * 4 + ['3'] * 4 + ['4'] * 2
    rng.shuffle(deck)
    width = height = 4
    board = Board(width=width, height=height, grid=tuple(deck))
    # The first two Jacks revealed are the starting positions for Player 1 and Player 2.
    jack_positions = [coord for coord in board.coords() if board.at(*coord) == 'J']
    if len(jack_positions) < 2:
        raise ValueError('Invalid deck: expected two Jacks')
    p1_start, p2_start = jack_positions[0], jack_positions[1]
    return board, p1_start, p2_start


def deal_board_3x3(seed: Optional[int] = None) -> Tuple[Board, Coord, Coord]:
    """Creates and deals a 3x3 board with a modified 9-card deck."""
    rng = random.Random(seed)
    # Deck composition for a 3x3 board.
    deck: List[Card] = ['J', 'J'] + ['A'] * 4 + ['2'] * 3
    rng.shuffle(deck)
    width = height = 3
    board = Board(width=width, height=height, grid=tuple(deck))
    jack_positions = [coord for coord in board.coords() if board.at(*coord) == 'J']
    if len(jack_positions) < 2:
        raise ValueError('Invalid deck: expected two Jacks')
    p1_start, p2_start = jack_positions[0], jack_positions[1]
    return board, p1_start, p2_start