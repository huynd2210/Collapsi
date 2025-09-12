from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request, send_from_directory

# Ensure package imports work when executed directly from repo root or as module
if __package__ in (None, ""):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Use relative imports inside the Collapsi namespace package
try:
    from .collapsi_core.board import Board
    from .collapsi_core.state import GameState
    from .collapsi_core.normalize import _shift_coord, _shift_grid_str
    from .collapsi_core.hashkey import _raw_state_key
    from .collapsi_core.solved_reader import (
        iter_records as _viz_iter_records,
        load_norm_index as _viz_load_index,
        IndexRecord as _VizIndexRecord,
    )
except Exception:
    from Collapsi.collapsi_core.board import Board  # type: ignore
    from Collapsi.collapsi_core.state import GameState  # type: ignore
    from Collapsi.collapsi_core.normalize import _shift_coord, _shift_grid_str  # type: ignore
    from Collapsi.collapsi_core.hashkey import _raw_state_key  # type: ignore
    from Collapsi.collapsi_core.solved_reader import (  # type: ignore
        iter_records as _viz_iter_records,
        load_norm_index as _viz_load_index,
        IndexRecord as _VizIndexRecord,
    )

# Optional lazy index builder (won't fail if not available)
try:
    from .collapsi_core.index_builder import (
        ensure_index_async as _ensure_index_async,
        index_status as _index_status,
    )
except Exception:
    try:
        from Collapsi.collapsi_core.index_builder import (  # type: ignore
            ensure_index_async as _ensure_index_async,      # type: ignore
            index_status as _index_status,                  # type: ignore
        )
    except Exception:
        _ensure_index_async = None  # type: ignore
        _index_status = None  # type: ignore

DEFAULT_DB = os.getenv("COLLAPSI_DB", "data/solved_norm.merged.db")

# Serve static assets from Collapsi/static (explicit absolute path)
STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))
app = Flask(__name__, static_url_path="/static", static_folder=STATIC_DIR)


def _abs_path(p: Optional[str], default_rel: str) -> str:
    if not p:
        return os.path.join(os.getcwd(), default_rel)
    if os.path.isabs(p):
        return p
    norm = p.replace("\\", "/")
    if norm.lower().startswith("collapsi/"):
        norm = norm.split("/", 1)[1]
    return os.path.join(os.getcwd(), norm)


def _candidate_index_paths() -> List[str]:
    return [
        os.path.join("data", "norm_index.db"),
        os.path.join("data", "norm_index.merged.db"),
    ]


def _autodetect_index_path() -> Optional[str]:
    for rel in _candidate_index_paths():
        try:
            p = _abs_path(rel, "")
            if os.path.isfile(p):
                return p
        except Exception:
            pass
    return None


# -------- DB path resolution (better UX when default DB is missing) --------

def _db_candidate_paths() -> List[str]:
    # Common places users might put the merged DB
    return [
        os.path.join("data", "solved_norm.merged.db"),
        os.path.join("data", "solved_norm.db"),
        os.path.join("Collapsi", "data", "solved_norm.merged.db"),
        os.path.join("Collapsi", "data", "solved_norm.db"),
        os.path.join("out", "solved_norm.merged.db"),
        os.path.join("Collapsi", "out", "solved_norm.merged.db"),
    ]


def _autodetect_db_path() -> Optional[str]:
    # 1) Fast scan of common candidates
    for rel in _db_candidate_paths():
        try:
            p = _abs_path(rel, "")
            if os.path.isfile(p):
                return p
        except Exception:
            pass
    # 2) Shallow walk to find any solved_norm*.db (best effort)
    try:
        roots = [os.getcwd(), os.path.join(os.getcwd(), "Collapsi")]
        for root in roots:
            for dirpath, dirnames, filenames in os.walk(root):
                for name in filenames:
                    if name.startswith("solved_norm") and name.endswith(".db"):
                        p = os.path.join(dirpath, name)
                        if os.path.isfile(p):
                            return p
                # Don't walk too deep
                if dirpath.count(os.sep) - root.count(os.sep) > 3:
                    del dirnames[:]  # prune
    except Exception:
        pass
    return None


def _resolve_db_or_suggest(p_opt: Optional[str]) -> Tuple[Optional[str], List[str]]:
    if p_opt:
        p = _abs_path(p_opt, "")
        if os.path.isfile(p):
            return p, []
    hits: List[str] = []
    for rel in _db_candidate_paths():
        try:
            p = _abs_path(rel, "")
            if os.path.isfile(p):
                hits.append(p)
        except Exception:
            pass
    if hits:
        return hits[0], hits
    probe = _autodetect_db_path()
    if probe:
        return probe, [probe]
    # Nothing found — suggest the preferred default under repo root
    return None, [_abs_path(os.path.join("data", "solved_norm.merged.db"), "")]


def _first_rc(mask: int) -> Tuple[int, int]:
    for i in range(16):
        if mask & (1 << i):
            return (i // 4, i % 4)
    return (0, 0)


def _bits_to_coords(mask: int) -> Tuple[Tuple[int, int], ...]:
    out: List[Tuple[int, int]] = []
    for i in range(16):
        if mask & (1 << i):
            out.append((i // 4, i % 4))
    return tuple(out)


def _grid_from_bits(a: int, b2: int, b3: int, b4: int) -> Tuple[str, ...]:
    grid: List[str] = []
    for i in range(16):
        bit = 1 << i
        if a & bit:
            grid.append("A")
        elif b2 & bit:
            grid.append("2")
        elif b3 & bit:
            grid.append("3")
        elif b4 & bit:
            grid.append("4")
        else:
            grid.append("A")
    return tuple(grid)


def _state_from_index_rec(idx: _VizIndexRecord, turn: int) -> GameState:
    grid = _grid_from_bits(idx.a, idx.b2, idx.b3, idx.b4)
    board = Board(width=4, height=4, grid=grid)
    p1 = _first_rc(idx.x)
    p2 = _first_rc(idx.o)
    collapsed = _bits_to_coords(idx.c)
    return GameState(board=board, collapsed=collapsed, p1=p1, p2=p2, turn=int(turn))


# ---------- Static routes ----------

@app.get("/")
def index() -> Any:
    return send_from_directory(app.static_folder, "index.html")


@app.get("/viz")
def viz() -> Any:
    # Auto-start index build in background if missing to enable overlays in /viz
    try:
        if _ensure_index_async:
            db = _autodetect_db_path() or _abs_path(DEFAULT_DB, "")
            if db and os.path.isfile(db):
                default_index_abs = _abs_path(os.path.join("data", "norm_index.db"), "")
                if not os.path.isfile(default_index_abs):
                    _ensure_index_async(db, default_index_abs)
    except Exception:
        # Non-fatal: still serve the page; viz.js will poll /api/index/status and /api/solved/page
        pass
    return send_from_directory(app.static_folder, "viz.html")


@app.get("/viz.js")
def viz_js() -> Any:
    resp = send_from_directory(app.static_folder, "viz.js")
    try:
        resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    except Exception:
        pass
    return resp


@app.get("/main.js")
def main_js() -> Any:
    resp = send_from_directory(app.static_folder, "main.js")
    try:
        resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    except Exception:
        pass
    return resp


@app.get("/styles.css")
def styles_css() -> Any:
    resp = send_from_directory(app.static_folder, "styles.css")
    try:
        resp.headers["Content-Type"] = "text/css; charset=utf-8"
    except Exception:
        pass
    return resp

@app.get("/static/<path:filename>")
def static_files(filename: str) -> Any:
    # Fallback explicit static file handler so /static/* always serves from Collapsi/static
    return send_from_directory(app.static_folder, filename)

# ---------- Core Game API (required by main.js) ----------

# Import the game facade (preserves original behavior and DB-backed solve)
try:
    from .game import (  # type: ignore
        Board as GBoard,
        GameState as GGameState,
        deal_board_3x3,
        deal_board_4x4,
        legal_moves as g_legal_moves,
        apply_move as g_apply_move,
        solve_with_cache as g_solve_with_cache,
        choose_ai_side_for_board,
        ai_pick_move as g_ai_pick_move,
        find_example_path as g_find_example_path,
        solve_moves_cpp as g_solve_moves_cpp,
        normalize_for_torus_view as g_normalize_for_torus_view,
    )
except Exception:
    from Collapsi.game import (  # type: ignore
        Board as GBoard,
        GameState as GGameState,
        deal_board_3x3,
        deal_board_4x4,
        legal_moves as g_legal_moves,
        apply_move as g_apply_move,
        solve_with_cache as g_solve_with_cache,
        choose_ai_side_for_board,
        ai_pick_move as g_ai_pick_move,
        find_example_path as g_find_example_path,
        solve_moves_cpp as g_solve_moves_cpp,
        normalize_for_torus_view as g_normalize_for_torus_view,
    )


def _board_to_json(b: GBoard) -> Dict[str, Any]:
    return {"width": int(b.width), "height": int(b.height), "grid": list(b.grid)}


def _state_to_json(s: GGameState, ai_side: Optional[int] = None, human_side: Optional[int] = None) -> Dict[str, Any]:
    return {
        "board": _board_to_json(s.board),
        "collapsed": [[int(r), int(c)] for (r, c) in s.collapsed],
        "p1": [int(s.p1[0]), int(s.p1[1])],
        "p2": [int(s.p2[0]), int(s.p2[1])],
        "turn": int(s.turn),
        "aiSide": ai_side,
        "humanSide": human_side,
    }


def _json_to_state(obj: Dict[str, Any]) -> GGameState:
    b = obj["board"]
    board = GBoard(width=int(b["width"]), height=int(b["height"]), grid=tuple(str(x) for x in b["grid"]))
    collapsed = tuple((int(r), int(c)) for r, c in obj.get("collapsed", []))
    p1r, p1c = obj["p1"]
    p2r, p2c = obj["p2"]
    turn = int(obj["turn"])
    return GGameState(board=board, collapsed=collapsed, p1=(int(p1r), int(p1c)), p2=(int(p2r), int(p2c)), turn=turn)


@app.post("/api/new")
def api_new() -> Any:
    body = request.get_json(force=True, silent=True) or {}
    size = str(body.get("size", "4"))
    seed = body.get("seed", None)
    db_path = DEFAULT_DB
    if size == "3":
        board, p1, p2 = deal_board_3x3(seed=seed)
    else:
        board, p1, p2 = deal_board_4x4(seed=seed)
    ai_side = int(choose_ai_side_for_board(board, p1, p2, db_path))
    human_side = 2 if ai_side == 1 else 1
    state = GGameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=1)
    return jsonify({
        "ok": True,
        "state": _state_to_json(state, ai_side=ai_side, human_side=human_side),
        "legalMoves": g_legal_moves(state),
    })

@app.post("/api/new_from")
def api_new_from() -> Any:
    body = request.get_json(force=True, silent=True) or {}
    s_in = body.get("state")
    if not isinstance(s_in, dict):
        return jsonify({"ok": False, "error": "state required"}), 400
    try:
        b = s_in["board"]
        board = GBoard(
            width=int(b["width"]),
            height=int(b["height"]),
            grid=tuple(str(x) for x in b["grid"]),
        )
        collapsed = tuple((int(r), int(c)) for r, c in s_in.get("collapsed", []))
        p1 = (int(s_in["p1"][0]), int(s_in["p1"][1]))
        p2 = (int(s_in["p2"][0]), int(s_in["p2"][1]))
        turn_in = int(s_in.get("turn", 1))  # viz uses 0/1; game uses 1/2
        # Map 0->1 (X), 1->2 (O)
        if turn_in in (0, 1):
            turn = 1 if turn_in == 0 else 2
        else:
            turn = 1 if turn_in not in (1, 2) else turn_in
        state = GGameState(board=board, collapsed=collapsed, p1=p1, p2=p2, turn=turn)
    except Exception as e:
        return jsonify({"ok": False, "error": f"bad state: {e}"}), 400

    db_path = DEFAULT_DB
    try:
        ai_side = int(choose_ai_side_for_board(board, p1, p2, db_path))
        if ai_side not in (1, 2):
            ai_side = 2 if turn == 1 else 1
    except Exception:
        ai_side = 2 if turn == 1 else 1
    human_side = 2 if ai_side == 1 else 1

    legal = g_legal_moves(state)
    return jsonify({
        "ok": True,
        "state": _state_to_json(state, ai_side=ai_side, human_side=human_side),
        "legalMoves": legal,
    })


@app.post("/api/legal")
def api_legal() -> Any:
    body = request.get_json(force=True)
    state = _json_to_state(body["state"])
    return jsonify({"ok": True, "legalMoves": g_legal_moves(state)})


@app.post("/api/move")
def api_move() -> Any:
    body = request.get_json(force=True)
    state = _json_to_state(body["state"])
    move = tuple(body["move"])  # type: ignore
    legal = g_legal_moves(state)
    if move not in legal:
        return jsonify({"ok": False, "error": "Illegal move", "legalMoves": legal}), 400
    next_state = g_apply_move(state, move)
    return jsonify({"ok": True, "state": _state_to_json(next_state), "legalMoves": g_legal_moves(next_state)})


@app.post("/api/ai")
def api_ai() -> Any:
    body = request.get_json(force=True)
    state = _json_to_state(body["state"])
    db_path = DEFAULT_DB
    move = g_ai_pick_move(state, db_path)
    legal = g_legal_moves(state)
    if move is None:
        # Try detailed solver if available
        detailed = g_solve_moves_cpp(state)
        if not detailed:
            return jsonify({"ok": False, "error": "C++ solver unavailable (no per-move data)."}), 500
        wins = [it for it in detailed if bool(it.get("win"))]
        def pl_min(it): return it.get("plies") if isinstance(it.get("plies"), int) else 10**9
        def pl_max(it): return it.get("plies") if isinstance(it.get("plies"), int) else -1
        chosen = min(wins, key=pl_min) if wins else max(detailed, key=pl_max)
        mv = chosen.get("move") if isinstance(chosen, dict) else None
        if isinstance(mv, list) and len(mv) == 2:
            move = (int(mv[0]), int(mv[1]))
    if move is None or move not in legal:
        return jsonify({"ok": False, "error": "No AI move available"}), 500
    next_state = g_apply_move(state, move)
    winner = None
    if len(g_legal_moves(next_state)) == 0:
        winner = state.turn  # mover wins
    return jsonify({
        "ok": True,
        "move": move,
        "state": _state_to_json(next_state),
        "legalMoves": g_legal_moves(next_state),
        "winner": winner,
    })


@app.post("/api/solve")
def api_solve() -> Any:
    body = request.get_json(force=True)
    state = _json_to_state(body["state"])
    res = g_solve_with_cache(state, DEFAULT_DB)
    nb, p1, p2, col, dr, dc = g_normalize_for_torus_view(state)
    normalized = {
        "board": _board_to_json(nb),
        "p1": [p1[0], p1[1]],
        "p2": [p2[0], p2[1]],
        "collapsed": [[r, c] for (r, c) in col],
        "shift": {"dr": dr, "dc": dc},
    }
    return jsonify({
        "ok": True,
        "win": bool(res.win),
        "best": res.best_move,
        "plies": res.plies,
        "normalized": normalized,
    })


@app.post("/api/solve_moves")
def api_solve_moves() -> Any:
    body = request.get_json(force=True)
    state = _json_to_state(body["state"])
    detailed = g_solve_moves_cpp(state)
    if not detailed:
        return jsonify({"ok": False, "error": "C++ solver unavailable for per-move outcomes"}), 500
    return jsonify({"ok": True, "moves": detailed})
# ---------- Visualization APIs (DB stats, paging, overlays) ----------

@app.post("/api/solved/stats")
def api_solved_stats() -> Any:
    body = request.get_json(force=True, silent=True) or {}
    db_in = body.get("db")
    db, suggested = _resolve_db_or_suggest(db_in if isinstance(db_in, str) else None)
    if not db or not os.path.isfile(db):
        return jsonify({
            "ok": False,
            "error": "Solved DB not found. Provide a valid path in the DB field.",
            "suggestedDb": (suggested[0] if suggested else None),
            "suggestedPaths": suggested,
        }), 404
    limit = body.get("limit", None)
    if isinstance(limit, int) and limit <= 0:
        limit = None
    try:
        total = 0
        turns = {0: 0, 1: 0}
        wins = {0: 0, 1: 0}  # per-record: 1 = mover-to-move has a winning line; 0 = losing line
        plies_min: Optional[int] = None
        plies_max: Optional[int] = None
        plies_sum = 0
        # Overall winner counts across all records (sums to total if no draws)
        x_overall_wins = 0
        o_overall_wins = 0

        for rec in _viz_iter_records(db, start=0, limit=limit):
            total += 1
            t = int(rec.turn)
            w = int(rec.win)
            p = int(rec.plies)
            turns[t] = turns.get(t, 0) + 1
            wins[w] = wins.get(w, 0) + 1

            # Determine eventual winner (from the perspective of the side to move)
            # mover wins => winner = mover side; mover loses => winner = opponent side
            if (t == 0 and w == 1) or (t == 1 and w == 0):
                x_overall_wins += 1
            else:
                # Either (t==1 and w==1) or (t==0 and w==0) -> O overall win
                o_overall_wins += 1

            if plies_min is None or p < plies_min:
                plies_min = p
            if plies_max is None or p > plies_max:
                plies_max = p
            plies_sum += p

        avg_plies = (plies_sum / total) if total > 0 else None

        # Per-mover conditional win rates (X to move, O to move)
        x_total = int(turns.get(0, 0))
        o_total = int(turns.get(1, 0))
        x_wins_cond = 0
        o_wins_cond = 0
        for rec2 in _viz_iter_records(db, start=0, limit=limit):
            if int(rec2.win) == 1:
                if int(rec2.turn) == 0:
                    x_wins_cond += 1
                else:
                    o_wins_cond += 1
        x_rate = (x_wins_cond / x_total) if x_total > 0 else None
        o_rate = (o_wins_cond / o_total) if o_total > 0 else None

        # Overall win share by side (sums to ~100% if no draws)
        share_x = (x_overall_wins / total) if total > 0 else None
        share_o = (o_overall_wins / total) if total > 0 else None

        return jsonify({
            "ok": True,
            "total": total,
            "turns": {"X": int(turns.get(0, 0)), "O": int(turns.get(1, 0))},
            "wins": {"loss": int(wins.get(0, 0)), "win": int(wins.get(1, 0))},
            "winsByTurn": {"X": x_wins_cond, "O": o_wins_cond},
            # Back-compat: keep winRate, but add clearer names
            "winRate": {"X": x_rate, "O": o_rate},
            "moverWinRate": {"X": x_rate, "O": o_rate},  # conditional on mover to move
            "overallWinShare": {"X": share_x, "O": share_o},  # across all records; should sum to ~1.0
            "winnerCounts": {"X": x_overall_wins, "O": o_overall_wins},
            "plies": {"min": plies_min, "avg": avg_plies, "max": plies_max},
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/api/solved/page")
def api_solved_page() -> Any:
    body = request.get_json(force=True, silent=True) or {}
    db_in = body.get("db")
    db, suggested = _resolve_db_or_suggest(db_in if isinstance(db_in, str) else None)
    if not db or not os.path.isfile(db):
        return jsonify({
            "ok": False,
            "error": "Solved DB not found. Provide a valid path in the DB field.",
            "suggestedDb": (suggested[0] if suggested else None),
            "suggestedPaths": suggested,
        }), 404
    index_path = body.get("index", None)
    offset = int(body.get("offset", 0))
    limit = int(body.get("limit", 50))
    if limit <= 0:
        limit = 50

    index_used_path: Optional[str] = None
    try:
        if index_path:
            p = _abs_path(index_path, "")
            if os.path.isfile(p):
                idx_map = _viz_load_index(p)
                index_used_path = p
            else:
                idx_map = {}
        else:
            p = _autodetect_index_path()
            if p and os.path.isfile(p):
                idx_map = _viz_load_index(p)
                index_used_path = p
            else:
                idx_map = {}
    except Exception:
        idx_map = {}
        index_used_path = None

    try:
        items: List[Dict[str, Any]] = []
        for rec in _viz_iter_records(db, start=offset, limit=limit):
            entry: Dict[str, Any] = {
                "keyHex": f"{int(rec.key):016x}",
                "turn": int(rec.turn),
                "win": int(rec.win),
                "plies": int(rec.plies),
                "best": int(rec.best),
            }
            idx = idx_map.get((int(rec.key), int(rec.turn)))
            if idx:
                st = _state_from_index_rec(idx, rec.turn)
                entry["state"] = {
                    "board": {"width": st.board.width, "height": st.board.height, "grid": list(st.board.grid)},
                    "collapsed": [[r, c] for (r, c) in st.collapsed],
                    "p1": [st.p1[0], st.p1[1]],
                    "p2": [st.p2[0], st.p2[1]],
                    "turn": st.turn,
                }
            else:
                entry["state"] = None
            items.append(entry)

        # If no index loaded and builder exists, kick off lazy build in background
        index_build = None
        if not index_used_path and _ensure_index_async:
            try:
                default_index_abs = _abs_path(os.path.join("data", "norm_index.db"), "")
                index_build = _ensure_index_async(db, default_index_abs)
                index_used_path = default_index_abs
            except Exception as _e:
                index_build = {"started": False, "available": False, "error": str(_e)}

        return jsonify({"ok": True, "items": items, "offset": offset, "limit": limit, "indexPath": index_used_path, "indexBuild": index_build})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/api/index/status")
def api_index_status() -> Any:
    if not _index_status:
        return jsonify({"ok": True, "running": False, "index": {"bytes": None, "records": None, "recSize": None}, "dbTotalRecords": None})
    body = request.get_json(force=True, silent=True) or {}
    db_in = body.get("db")
    db, suggested = _resolve_db_or_suggest(db_in if isinstance(db_in, str) else None)
    if not db or not os.path.isfile(db):
        return jsonify({
            "ok": True,
            "running": False,
            "index": {"bytes": None, "records": None, "recSize": None},
            "dbTotalRecords": None,
            "suggestedDb": (suggested[0] if suggested else None),
            "suggestedPaths": suggested,
        })
    index_path = body.get("index", os.path.join("data", "norm_index.db"))
    try:
        p = _abs_path(index_path, "")
        # Proactively kick off index build if file is missing so the client doesn't need to guess
        if _ensure_index_async and not os.path.isfile(p):
            try:
                _ensure_index_async(db, p)
            except Exception:
                # Ignore; status call will still report running=False and bytes=None
                pass
        status = _index_status(db, p)
        return jsonify(status)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/api/solved/raw_variants")
def api_solved_raw_variants() -> Any:
    body = request.get_json(force=True, silent=True) or {}
    key_hex = str(body.get("keyHex", "")).strip().lower()
    turn = int(body.get("turn", 0))
    index_path = body.get("index", None)
    norm2raw_dir = body.get("norm2rawDir", os.path.join("cpp", "data", "norm2raw"))

    if not key_hex:
        return jsonify({"ok": False, "error": "keyHex required"}), 400

    try:
        idx_map = {}
        if index_path:
            idx_map = _viz_load_index(_abs_path(index_path, ""))
        else:
            p = _autodetect_index_path()
            if p:
                idx_map = _viz_load_index(p)
        if not idx_map:
            return jsonify({"ok": False, "error": "index not provided and auto-detect failed (expected data/norm_index.db)"}), 404
    except Exception as e:
        return jsonify({"ok": False, "error": f"failed to load index: {e}"}), 500

    key_int = int(key_hex, 16)
    norm = idx_map.get((key_int, turn))
    if not norm:
        return jsonify({"ok": False, "error": "normalized key not found in index"}), 404

    norm_state = _state_from_index_rec(norm, turn)

    n2r_path = _abs_path(os.path.join(norm2raw_dir, f"{key_hex}-{turn}.txt"), "")
    # If norm2raw mapping file is missing, synthesize it (enumerate all 16 torus shifts)
    try:
        if not os.path.exists(n2r_path):
            os.makedirs(os.path.dirname(n2r_path), exist_ok=True)
            w_s = norm_state.board.width
            h_s = norm_state.board.height
            ng = tuple(norm_state.board.grid)
            np2 = norm_state.p2
            ncoll = tuple(norm_state.collapsed)
            with open(n2r_path, "w", encoding="utf-8") as f:
                for dr in range(h_s):
                    for dc in range(w_s):
                        shifted = _shift_grid_str(ng, w_s, h_s, dr, dc)
                        b = Board(width=w_s, height=h_s, grid=tuple(shifted))
                        p1s = (dr, dc)
                        p2s = _shift_coord(np2, dr, dc, w_s, h_s)
                        colls = tuple(sorted(_shift_coord(c, dr, dc, w_s, h_s) for c in ncoll))
                        rs = GameState(board=b, collapsed=colls, p1=p1s, p2=p2s, turn=turn)
                        f.write(_raw_state_key(rs) + "\n")
    except Exception:
        # Non-fatal: continue and build the variants in-memory below
        pass

    # Build variants in-memory (16 torus shifts), compute rawKey for each
    results: List[Dict[str, Any]] = []
    w = norm_state.board.width
    h = norm_state.board.height
    norm_grid = tuple(norm_state.board.grid)
    norm_p2 = norm_state.p2
    norm_coll = tuple(norm_state.collapsed)

    for dr in range(h):
        for dc in range(w):
            shifted_grid = _shift_grid_str(norm_grid, w, h, dr, dc)
            board = Board(width=w, height=h, grid=tuple(shifted_grid))
            p1 = (dr, dc)
            p2 = _shift_coord(norm_p2, dr, dc, w, h)
            collapsed = tuple(sorted(_shift_coord(c, dr, dc, w, h) for c in norm_coll))
            raw_state = GameState(board=board, collapsed=collapsed, p1=p1, p2=p2, turn=turn)
            rk = _raw_state_key(raw_state)
            rk_hex = rk.split("|")[0] if "|" in rk else f"{0:016x}"
            results.append({
                "rawKey": rk_hex,
                "dr": dr,
                "dc": dc,
                "state": {
                    "board": {"width": w, "height": h, "grid": list(board.grid)},
                    "collapsed": [[r, c] for (r, c) in collapsed],
                    "p1": [p1[0], p1[1]],
                    "p2": [p2[0], p2[1]],
                    "turn": turn,
                },
            })

    return jsonify({"ok": True, "variants": results})


@app.post("/api/solved/find")
def api_solved_find() -> Any:
    body = request.get_json(force=True, silent=True) or {}
    db_in = body.get("db")
    db, suggested = _resolve_db_or_suggest(db_in if isinstance(db_in, str) else None)
    if not db or not os.path.isfile(db):
        return jsonify({
            "ok": False,
            "error": "Solved DB not found.",
            "suggestedDb": (suggested[0] if suggested else None),
            "suggestedPaths": suggested,
        }), 404
    index_path = body.get("index", None)
    s_in = body.get("state")
    if not s_in:
        return jsonify({"ok": False, "error": "missing state"}), 400
    try:
        b = s_in["board"]
        state = GameState(
            board=Board(width=int(b["width"]), height=int(b["height"]), grid=tuple(str(x) for x in b["grid"])),
            collapsed=tuple((int(r), int(c)) for r, c in s_in.get("collapsed", [])),
            p1=(int(s_in["p1"][0]), int(s_in["p1"][1])),
            p2=(int(s_in["p2"][0]), int(s_in["p2"][1])),
            turn=int(s_in["turn"]),
        )
    except Exception as e:
        return jsonify({"ok": False, "error": f"bad state: {e}"}), 400

    # Minimal linear scan placeholder (key recomputation could be added if needed)
    try:
        for _rec in _viz_iter_records(db, start=0, limit=None):
            break
        return jsonify({"ok": True, "found": False})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# Entrypoint for "python -m Collapsi.app"
if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", os.getenv("DEBUG", "0")).lower() in ("1", "true", "yes", "on")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=debug)