from __future__ import annotations

import random
from dataclasses import dataclass
import subprocess
import os
import sqlite3
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Set, Iterable, Any


# -------- Collapsi core model --------


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

    def pretty(self, p1: Optional[Coord] = None, p2: Optional[Coord] = None, collapsed: Optional[Set[Coord]] = None) -> str:
        """Generates a human-readable string representation of the board state."""
        lines: List[str] = []
        collapsed = collapsed or set()
        for r in range(self.height):
            row: List[str] = []
            for c in range(self.width):
                cell = self.at(r, c)
                if (r, c) in collapsed:
                    row.append('·')
                elif p1 == (r, c) and p2 == (r, c):
                    row.append('*')
                elif p1 == (r, c):
                    row.append('X')
                elif p2 == (r, c):
                    row.append('O')
                else:
                    row.append(cell)
            lines.append(' '.join(row))
        return '\n'.join(lines)


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


def card_steps(card: Card) -> int:
    """Determines the number of steps a player can move based on the card value."""
    if card == 'J' or card == 'A':
        return 1
    return int(card)


@dataclass(frozen=True)
class GameState:
    """Represents the dynamic state of the game, including player positions and collapsed cards."""
    board: Board
    collapsed: Tuple[Coord, ...]  # An immutable set of collapsed coordinates, sorted for consistent hashing.
    p1: Coord
    p2: Coord
    turn: int  # 1 or 2

    def is_collapsed(self, coord: Coord) -> bool:
        """Checks if a coordinate is collapsed."""
        return coord in set(self.collapsed)

    def other_player(self) -> int:
        """Returns the opponent of the current player."""
        return 2 if self.turn == 1 else 1

    def player_pos(self, player: int) -> Coord:
        """Returns the position of the specified player."""
        return self.p1 if player == 1 else self.p2

    def with_turn(self, next_turn: int) -> 'GameState':
        """Creates a new GameState with the turn updated."""
        return GameState(self.board, self.collapsed, self.p1, self.p2, next_turn)


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


@dataclass
class SolveResult:
    """Result of solving using the C++ engine."""
    win: bool
    best_move: Optional[Coord]
    proof_moves: Optional[Dict[GameState, Coord]]
    plies: Optional[int]


def opponent_move_count_after(state: GameState, my_move: Coord) -> int:
    """Calculates the number of legal moves the opponent has after a given move."""
    next_state = apply_move(state, my_move)
    return len(legal_moves(next_state))


def choose_child_by_heuristic(state: GameState, moves: List[Coord]) -> List[Coord]:
    """Deprecated: not used by solver; retained for compatibility in tests."""
    return sorted(moves)


def aostar_solve(state: GameState, *args: Any, **kwargs: Any) -> SolveResult:
    """Deprecated shim: redirect to C++ solver to prevent Python AO* usage."""
    return solve_with_cache(state, db_path=kwargs.get('db_path', 'collapsi.db'))


# -------- Persistence (SQLite) --------


def _ensure_db_dir(db_path: str) -> None:
    """Ensures the directory for the SQLite DB exists before connecting."""
    directory = os.path.dirname(db_path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


def _resolve_db_path(db_path: str) -> str:
    """Resolves a potentially unwritable DB path to a writable one, creating the directory if needed."""
    try:
        _ensure_db_dir(db_path)
        return db_path
    except PermissionError:
        pass
    # Try common writable locations
    candidates = [
        os.getenv('COLLAPSI_DB_DIR'),
        '/opt/render/project/src/data',
        os.path.join(os.getcwd(), 'data'),
        '/tmp',
    ]
    base = os.path.basename(db_path) or 'collapsi.db'
    for d in candidates:
        if not d:
            continue
        try:
            os.makedirs(d, exist_ok=True)
            return os.path.join(d, base)
        except Exception:
            continue
    # Last resort: current working directory
    return base


def _coord_to_str(c: Coord) -> str:
    """Converts a coordinate to a string for database storage."""
    return f"{c[0]},{c[1]}"


def _coords_to_str(collapsed: Tuple[Coord, ...]) -> str:
    """Converts a set of collapsed coordinates to a string."""
    return ';'.join(_coord_to_str(c) for c in collapsed)


def _state_key(state: GameState) -> str:
    """Generates a unique key for a game state for use in the database."""
    board_str = ''.join(state.board.grid)
    return '|'.join([
        f"{state.board.width}x{state.board.height}",
        board_str,
        _coord_to_str(state.p1),
        _coord_to_str(state.p2),
        _coords_to_str(state.collapsed),
        str(state.turn),
    ])


def _ensure_db(conn: sqlite3.Connection) -> None:
    """Ensures the database table for storing game states exists and is up to date."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS states (
            key TEXT PRIMARY KEY,
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            grid TEXT NOT NULL,
            p1 TEXT NOT NULL,
            p2 TEXT NOT NULL,
            collapsed TEXT NOT NULL,
            turn INTEGER NOT NULL,
            win INTEGER NOT NULL,
            best_move TEXT,
            solved_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    # Schema upgrade: add plies column if missing
    cur = conn.execute("PRAGMA table_info(states)")
    cols = [r[1] for r in cur.fetchall()]
    if 'plies' not in cols:
        conn.execute("ALTER TABLE states ADD COLUMN plies INTEGER")
    conn.commit()


def db_lookup_state(db_path: str, key: str) -> Optional[Tuple[bool, Optional[Coord], Optional[int]]]:
    """Looks up a solved state from the database."""
    resolved = _resolve_db_path(db_path)
    _ensure_db_dir(resolved)
    conn = sqlite3.connect(resolved)
    try:
        _ensure_db(conn)
        cur = conn.execute("SELECT win, best_move, plies FROM states WHERE key = ?", (key,))
        row = cur.fetchone()
        if not row:
            return None
        win_int, best_move_str, plies_val = row
        best_move: Optional[Coord]
        if best_move_str is None:
            best_move = None
        else:
            r_s, c_s = best_move_str.split(',')
            best_move = (int(r_s), int(c_s))
        plies: Optional[int] = int(plies_val) if plies_val is not None else None
        return (bool(win_int), best_move, plies)
    finally:
        conn.close()


def db_store_state(db_path: str, state: GameState, win: bool, best_move: Optional[Coord], plies: Optional[int]) -> None:
    """Stores a solved game state in the database."""
    resolved = _resolve_db_path(db_path)
    _ensure_db_dir(resolved)
    conn = sqlite3.connect(resolved)
    try:
        _ensure_db(conn)
        key = _state_key(state)
        best_move_str = _coord_to_str(best_move) if best_move is not None else None
        conn.execute(
            """
            INSERT OR REPLACE INTO states
            (key, width, height, grid, p1, p2, collapsed, turn, win, best_move, solved_at, plies)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                state.board.width,
                state.board.height,
                ''.join(state.board.grid),
                _coord_to_str(state.p1),
                _coord_to_str(state.p2),
                _coords_to_str(state.collapsed),
                state.turn,
                1 if win else 0,
                best_move_str,
                datetime.utcnow().isoformat(timespec='seconds') + 'Z',
                plies if plies is not None else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _find_cpp_exe() -> Optional[str]:
    base = os.path.dirname(__file__)
    candidates = [
        os.path.join(base, 'cpp', 'build', 'Release', 'collapsi_cpp.exe'),
        os.path.join(base, 'cpp', 'build-deploy', 'Release', 'collapsi_cpp.exe'),
        os.path.join(base, 'cpp', 'build', 'Release', 'collapsi_cpp'),
        os.path.join(base, 'cpp', 'build-deploy', 'Release', 'collapsi_cpp'),
        'collapsi_cpp',
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def _state_to_cpp_arg(state: GameState) -> str:
    # Only 4x4 supported by C++ solver
    w = state.board.width
    h = state.board.height
    if w != 4 or h != 4:
        raise ValueError('C++ solver supports 4x4 only')
    a = 0
    b2 = 0
    b3 = 0
    b4 = 0
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
    return f"{a:04x},{b2:04x},{b3:04x},{b4:04x},{x:04x},{o:04x},{c:04x},{turn:01x}"


def _decode_best_move_byte(val: int) -> Optional[Coord]:
    if val < 0 or val > 255:
        return None
    if val == 0xFF:
        return None
    to_idx = val & 0xF
    # Return destination coordinate only
    return (to_idx // 4, to_idx % 4)


def solve_with_cache(state: GameState, db_path: str, depth_cap: Optional[int] = None) -> SolveResult:
    """Solves a game state using the C++ solver; no Python AO* is used."""
    try:
        arg = _state_to_cpp_arg(state)
    except Exception:
        # Unsupported board size or malformed
        return SolveResult(win=False, best_move=None, proof_moves=None, plies=None)
    exe = _find_cpp_exe()
    if not exe:
        return SolveResult(win=False, best_move=None, proof_moves=None, plies=None)
    try:
        proc = subprocess.run([exe, '--state', arg], capture_output=True, text=True, check=False)
        line = (proc.stdout or '').strip()
        # expected: "win best plies timeus | m:p:w ..." or without the trailing list
        parts = line.split('|')
        head = parts[0].strip().split()
        if len(head) >= 3:
            win = (head[0] == '1')
            try:
                best_raw = int(head[1])
            except Exception:
                best_raw = 255
            best_coord = _decode_best_move_byte(best_raw)
            try:
                plies = int(head[2])
            except Exception:
                plies = None
            return SolveResult(win=win, best_move=best_coord, proof_moves=None, plies=plies)
    except Exception:
        pass
    return SolveResult(win=False, best_move=None, proof_moves=None, plies=None)


def solve_moves_cpp(state: GameState) -> List[Dict[str, Any]]:
    """Returns per-legal-move plies/win from the C++ solver's detailed output."""
    items: List[Dict[str, Any]] = []
    try:
        arg = _state_to_cpp_arg(state)
    except Exception:
        return items
    exe = _find_cpp_exe()
    if not exe:
        return items
    try:
        proc = subprocess.run([exe, '--state', arg], capture_output=True, text=True, check=False)
        line = (proc.stdout or '').strip()
        parts = line.split('|')
        if len(parts) < 2:
            return items
        tail = parts[1].strip()
        if not tail:
            return items
        for tok in tail.split():
            try:
                m_str, p_str, w_str = tok.split(':')
                m_val = int(m_str)
                p_val = int(p_str)
                w_val = int(w_str)
                to_idx = m_val & 0xF
                r = to_idx // 4
                c = to_idx % 4
                items.append({'move': [r, c], 'win': bool(w_val), 'plies': p_val})
            except Exception:
                continue
    except Exception:
        return items
    return items


def choose_ai_side_for_board(board: Board, p1: Coord, p2: Coord, db_path: str) -> int:
    """Determines which side the AI should play, based on which player has a cached win."""
    state_p1 = GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=1)
    res_p1 = solve_with_cache(state_p1, db_path)
    if res_p1.win:
        return 1
    state_p2 = GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=2)
    res_p2 = solve_with_cache(state_p2, db_path)
    return 2 if res_p2.win else 1  # Default to Player 1 if neither side has a cached win.


def ai_pick_move(state: GameState, db_path: str) -> Optional[Coord]:
    """Picks the best move for the AI by solving the current game state."""
    res = solve_with_cache(state, db_path)
    return res.best_move if res.win else None


# -------- CLI driver --------


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description='Collapsi AO* solver and DB-backed AI')
    parser.add_argument('--size', choices=['3', '4'], default='4', help='Board size (NxN): 3 or 4')
    parser.add_argument('--db', default='collapsi.db', help='SQLite DB file path')
    parser.add_argument('--seed', type=int, default=None, help='RNG seed for deal')
    parser.add_argument('--play', action='store_true', help='Play against DB-backed AI')
    parser.add_argument('--show-paths', action='store_true', help='Show orthogonal paths for moves')
    args = parser.parse_args()

    if args.size == '3':
        board, p1, p2 = deal_board_3x3(seed=args.seed)
    else:
        board, p1, p2 = deal_board_4x4(seed=args.seed)

    if not args.play:
        state = GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=1)
        print('Initial board:')
        print(board.pretty(p1, p2, set()))
        res = solve_with_cache(state, args.db)
        print('\nP1 has a forced win:' if res.win else '\nP1 cannot force a win:')
        if res.best_move is not None:
            print('Suggested move for P1:', res.best_move)
            if args.show_paths:
                path = find_example_path(state, res.best_move)
                if path is not None:
                    print('One valid orthogonal path:', path)
        return

    # Interactive play vs AI
    ai_side = choose_ai_side_for_board(board, p1, p2, args.db)
    human_side = 2 if ai_side == 1 else 1
    state = GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=1)
    print('Initial board:')
    print(board.pretty(p1, p2, set()))
    print(f"AI plays as Player {ai_side}. You are Player {human_side}.")

    def prompt_human_move(s: GameState) -> Coord:
        legal = legal_moves(s)
        if not legal:
            raise RuntimeError('No legal moves available')
        print('Your legal moves:', legal)
        while True:
            text = input('Enter your move as r,c or r c: ').strip()
            sep = ',' if ',' in text else ' '
            try:
                r_s, c_s = [t for t in text.split(sep) if t != '']
                move = (int(r_s), int(c_s))
            except Exception:
                print('Could not parse. Try again.')
                continue
            if move in legal:
                return move
            print('Illegal move. Try again.')

    while True:
        moves_me = legal_moves(state)
        if not moves_me:
            winner = state.other_player()
            print(f"Player {winner} wins!")
            break
        if state.turn == ai_side:
            move = ai_pick_move(state, args.db)
            if move is None:
                # Fallback: heuristic pick when no forced win known
                choices = choose_child_by_heuristic(state, moves_me)
                move = choices[0]
            print(f"AI moves to {move}")
            if args.show_paths:
                path = find_example_path(state, move)
                if path is not None:
                    print('AI path:', path)
            state = apply_move(state, move)
            print(board.pretty(state.p1, state.p2, set(state.collapsed)))
        else:
            move = prompt_human_move(state)
            if args.show_paths:
                path = find_example_path(state, move)
                if path is not None:
                    print('Your path:', path)
            state = apply_move(state, move)
            print(board.pretty(state.p1, state.p2, set(state.collapsed)))


if __name__ == '__main__':
    main()


