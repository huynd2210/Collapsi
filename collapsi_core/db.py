from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Optional, Tuple

from .board import Coord
from .state import GameState
from .hashkey import _state_key


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
    return f"{c[0]},{c[1]}"


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
            solved_at TEXT NOT NULL,
            plies INTEGER
        )
        """
    )
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
    """Stores a solved game state in the database. Uses compact key and stores minimal fields."""
    resolved = _resolve_db_path(db_path)
    _ensure_db_dir(resolved)
    conn = sqlite3.connect(resolved)
    try:
        _ensure_db(conn)
        key = _state_key(state)
        best_move_str = _coord_to_str(best_move) if best_move is not None else None
        # Store minimal columns; keep backward-compatible columns filled minimally
        conn.execute(
            """
            INSERT OR REPLACE INTO states
            (key, width, height, grid, p1, p2, collapsed, turn, win, best_move, solved_at, plies)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                4,
                4,
                '',
                '',
                '',
                '',
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