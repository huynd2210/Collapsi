from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple, Any

from .board import Board, Coord
from .state import GameState
from .db import db_store_state


def _find_cpp_exe() -> Optional[str]:
    """
    Resolve the native solver path with strong defaults for Render.
    Order:
    1) Explicit env vars: COLLAPSI_CPP_EXE, COLLAPSI_CPP (must exist and be executable)
    2) Well-known absolute path on Render: /opt/render/project/src/collapsi_cpp
    3) Common build outputs relative to codebase
    4) PATH lookup (collapsi_cpp[.exe])
    Set COLLAPSI_DEBUG=1 to print resolution trace.
    """
    debug = os.getenv('COLLAPSI_DEBUG', '0').lower() in ('1', 'true', 'yes', 'on')

    def _ok(path: str) -> bool:
        try:
            return os.path.exists(path) and os.access(path, os.X_OK)
        except Exception:
            return False

    # 1) Environment
    for env_var in ('COLLAPSI_CPP_EXE', 'COLLAPSI_CPP'):
        p = os.getenv(env_var)
        if p and _ok(p):
            if debug:
                print(f"[cpp] using {env_var}={p}")
            return p
        if p and debug:
            print(f"[cpp] {env_var} set but not executable: {p}")

    # 2) Render baked-in location
    render_default = '/opt/render/project/src/collapsi_cpp'
    if _ok(render_default):
        if debug:
            print(f"[cpp] found Render default {render_default}")
        return render_default
    elif debug:
        print(f"[cpp] Render default missing: {render_default}")

    # 3) Relative build outputs (relative to this file)
    base = os.path.dirname(os.path.dirname(__file__))  # package dir parent (Collapsi)
    candidates = [
        os.path.join(base, 'cpp', 'build', 'collapsi_cpp'),               # Linux Ninja/Unix Makefile
        os.path.join(base, 'cpp', 'build', 'Release', 'collapsi_cpp'),    # Linux Release dir
        os.path.join(base, 'cpp', 'build', 'collapsi_cpp.exe'),           # Windows
        os.path.join(base, 'cpp', 'build', 'Release', 'collapsi_cpp.exe'),
        os.path.join(base, 'cpp', 'build-ninja', 'collapsi_cpp'),
        os.path.join(base, 'cpp', 'build-ninja', 'collapsi_cpp.exe'),
        os.path.join(base, 'cpp', 'build-deploy', 'collapsi_cpp'),
        os.path.join(base, 'cpp', 'build-deploy', 'Release', 'collapsi_cpp.exe'),
    ]
    for p in candidates:
        if _ok(p):
            if debug:
                print(f"[cpp] found candidate {p}")
            return p
        elif debug:
            print(f"[cpp] missing candidate {p}")

    # 4) PATH
    for name in ('collapsi_cpp', 'collapsi_cpp.exe'):
        found = shutil.which(name)
        if found and _ok(found):
            if debug:
                print(f"[cpp] found in PATH: {found}")
            return found
        elif debug:
            print(f"[cpp] not in PATH: {name}")

    if debug:
        try:
            here = os.getcwd()
            print(f"[cpp] resolution failed; cwd={here}, files={os.listdir('.')}")
        except Exception:
            pass
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


def _parse_solver_head(line: str) -> Tuple[bool, Optional[int], Optional[int]]:
    """
    Parses the 'head' part of solver output: "win best plies".
    Returns (win, best_raw, plies).
    """
    parts = (line or "").strip().split('|')
    head = parts[0].strip().split()
    if len(head) < 3 or head[0] not in ('0', '1'):
        raise RuntimeError("C++ solver returned malformed output")
    win = (head[0] == '1')
    try:
        best_raw = int(head[1])
    except Exception:
        best_raw = 255
    try:
        plies = int(head[2])
    except Exception:
        plies = None
    return win, best_raw, plies


def _parse_moves_tail(tail: str) -> List[Dict[str, Any]]:
    """Parses the detailed per-move tail tokens: 'MM:PP:W'"""
    items: List[Dict[str, Any]] = []
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
    return items


def _run_cpp_default(exe: str, arg: str) -> str:
    proc = subprocess.run([exe, '--state', arg], capture_output=True, text=True, check=False)
    return (proc.stdout or '').strip()


@dataclass
class SolveResult:
    """Result of solving using the C++ engine."""
    win: bool
    best_move: Optional[Coord]
    proof_moves: Optional[Dict[GameState, Coord]]
    plies: Optional[int]


def solve_with_cache_impl(
    state: GameState,
    db_path: str,
    *,
    find_cpp_exe: Optional[Callable[[], Optional[str]]] = None,
    run_proc: Optional[Callable[[str, str], str]] = None,
    db_store: Optional[Callable[[str, GameState, bool, Optional[Coord], Optional[int]], None]] = None,
) -> SolveResult:
    """
    Canonical solver: must use the native C++ CLI. No heuristic or DB fallbacks.
    - Parses plies/best from the CLI and writes (win, plies) to SQLite under the normalized key.
    - Does not persist best_move because normalized keys omit raw alignment.
    """
    arg = _state_to_cpp_arg(state)  # may raise for non-4x4
    find_cpp_exe = find_cpp_exe or _find_cpp_exe
    run_proc = run_proc or _run_cpp_default
    db_store = db_store or db_store_state

    exe = find_cpp_exe()
    if not exe:
        raise RuntimeError("C++ solver executable not found. Build it and/or set COLLAPSI_CPP_EXE.")
    line = run_proc(exe, arg)
    win, best_raw, plies = _parse_solver_head(line)
    best_coord = _decode_best_move_byte(best_raw if best_raw is not None else 255)
    try:
        db_store(db_path, state, win=win, best_move=None, plies=plies)
    except Exception:
        pass
    return SolveResult(win=win, best_move=best_coord, proof_moves=None, plies=plies)


def solve_moves_cpp_impl(
    state: GameState,
    *,
    find_cpp_exe: Optional[Callable[[], Optional[str]]] = None,
    run_proc: Optional[Callable[[str, str], str]] = None,
) -> List[Dict[str, Any]]:
    """Returns per-legal-move plies/win from the C++ solver's detailed output."""
    try:
        arg = _state_to_cpp_arg(state)
    except Exception:
        return []
    find_cpp_exe = find_cpp_exe or _find_cpp_exe
    run_proc = run_proc or _run_cpp_default

    exe = find_cpp_exe()
    if not exe:
        return []
    try:
        line = run_proc(exe, arg)
        parts = line.split('|')
        if len(parts) < 2:
            return []
        tail = parts[1].strip()
        if not tail:
            return []
        return _parse_moves_tail(tail)
    except Exception:
        return []