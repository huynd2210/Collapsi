from __future__ import annotations

from typing import List, Tuple, Optional, Dict, Set, Iterable, Any

from .board import Board, Card, Coord
from .state import GameState


def card_steps(card: Card) -> int:
    """Determines the number of steps a player can move based on the card value."""
    if card == 'J' or card == 'A':
        return 1
    return int(card)


def wrap_step(board: Board, r: int, c: int) -> Coord:
    """Wraps coordinates around the board."""
    return r % board.height, c % board.width


def neighbors(board: Board, coord: Coord) -> List[Coord]:
    """Gets the orthogonal neighbors of a coordinate."""
    r, c = coord
    return [
        wrap_step(board, r - 1, c),
        wrap_step(board, r + 1, c),
        wrap_step(board, r, c - 1),
        wrap_step(board, r, c + 1),
    ]


def enumerate_destinations(state: GameState, start: Coord, steps: int, opponent: Coord) -> Set[Coord]:
    """
    Finds all possible destination coordinates for a player's move.
    This is done using a Depth First Search (DFS) to find all paths of a specific length.
    """
    results: Set[Coord] = set()
    visited_path: Set[Coord] = set([start])
    blocked: Set[Coord] = set(state.collapsed)

    def dfs(current: Coord, remaining: int) -> None:
        if remaining == 0:
            # A move must not land on the start or opponent's position.
            if current != start and current != opponent:
                results.add(current)
            return
        for nxt in neighbors(state.board, current):
            if nxt in blocked or nxt in visited_path:
                continue
            visited_path.add(nxt)
            dfs(nxt, remaining - 1)
            visited_path.remove(nxt)

    dfs(start, steps)
    return results


def legal_moves(state: GameState) -> List[Coord]:
    """Calculates all legal moves for the current player."""
    player = state.turn
    me = state.player_pos(player)
    opp = state.player_pos(state.other_player())
    start_card = state.board.at(*me)
    steps = card_steps(start_card)
    dests = enumerate_destinations(state, me, steps, opp)
    return sorted(dests)


def apply_move(state: GameState, dest: Coord) -> GameState:
    """Applies a move to the game state and returns the new state."""
    player = state.turn
    me = state.player_pos(player)
    opp = state.player_pos(state.other_player())
    # The player's starting card is collapsed.
    new_collapsed: Set[Coord] = set(state.collapsed)
    new_collapsed.add(me)
    if player == 1:
        return GameState(state.board, tuple(sorted(new_collapsed)), dest, opp, 2)
    else:
        return GameState(state.board, tuple(sorted(new_collapsed)), opp, dest, 1)


def find_example_path(state: GameState, dest: Coord) -> Optional[List[Coord]]:
    """Finds an example of a valid orthogonal path for a given move."""
    me = state.player_pos(state.turn)
    opp = state.player_pos(state.other_player())
    steps = card_steps(state.board.at(*me))
    blocked: Set[Coord] = set(state.collapsed)

    visited: Set[Coord] = set([me])
    path: List[Coord] = [me]
    found: Optional[List[Coord]] = None

    def dfs(current: Coord, remaining: int) -> None:
        nonlocal found
        if found is not None:
            return
        if remaining == 0:
            if current == dest and current != me and current != opp:
                found = list(path)
            return
        for nxt in neighbors(state.board, current):
            if nxt in blocked or nxt in visited:
                continue
            visited.add(nxt)
            path.append(nxt)
            dfs(nxt, remaining - 1)
            path.pop()
            visited.remove(nxt)

    dfs(me, steps)
    return found


def opponent_move_count_after(state: GameState, my_move: Coord) -> int:
    """Calculates the number of legal moves the opponent has after a given move."""
    next_state = apply_move(state, my_move)
    return len(legal_moves(next_state))


def choose_child_by_heuristic(state: GameState, moves: List[Coord]) -> List[Coord]:
    """Deprecated: not used by solver; retained for compatibility in tests."""
    return sorted(moves)