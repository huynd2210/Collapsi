from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple, Optional

from flask import Flask, request, jsonify, send_from_directory, send_file
import logging
import logging.handlers
import io
import zipfile
import uuid

from game import (
    Board,
    GameState,
    deal_board_3x3,
    deal_board_4x4,
    legal_moves,
    apply_move,
    solve_with_cache,
    choose_ai_side_for_board,
    ai_pick_move,
    find_example_path,
    db_lookup_state,
    db_store_state,
    _state_key,
    solve_moves_cpp,
    normalize_for_torus_view,
)


DEFAULT_DB = os.getenv('COLLAPSI_DB', 'collapsi.db')


def board_to_json(board: Board) -> Dict[str, Any]:
    """Serializes a Board object to a JSON-compatible dictionary."""
    return {
        'width': board.width,
        'height': board.height,
        'grid': list(board.grid),
    }


def board_from_json(data: Dict[str, Any]) -> Board:
    """Deserializes a JSON dictionary to a Board object."""
    width = int(data['width'])
    height = int(data['height'])
    grid = tuple(str(x) for x in data['grid'])
    return Board(width=width, height=height, grid=grid)


def state_to_json(state: GameState, ai_side: int | None = None, human_side: int | None = None) -> Dict[str, Any]:
    """Serializes a GameState object to a JSON-compatible dictionary."""
    return {
        'board': board_to_json(state.board),
        'collapsed': [[r, c] for (r, c) in state.collapsed],
        'p1': [state.p1[0], state.p1[1]],
        'p2': [state.p2[0], state.p2[1]],
        'turn': state.turn,
        'aiSide': ai_side,
        'humanSide': human_side,
    }


def json_to_state(data: Dict[str, Any]) -> GameState:
    """Deserializes a JSON dictionary to a GameState object."""
    board = board_from_json(data['board'])
    collapsed = tuple((int(r), int(c)) for r, c in data.get('collapsed', []))
    p1r, p1c = data['p1']
    p2r, p2c = data['p2']
    turn = int(data['turn'])
    return GameState(board=board, collapsed=collapsed, p1=(int(p1r), int(p1c)), p2=(int(p2r), int(p2c)), turn=turn)


app = Flask(__name__, static_url_path='', static_folder='static')

# Basic JSON-style logging to stdout (cloud-friendly)
_logger = logging.getLogger("collapsi")
if not _logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(message)s')
    handler.setFormatter(formatter)
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)

# File logging with daily rotation
LOG_DIR = os.getenv('COLLAPSI_LOG_DIR', os.path.join(os.getcwd(), 'logs'))
try:
    os.makedirs(LOG_DIR, exist_ok=True)
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=os.path.join(LOG_DIR, 'collapsi.log'), when='midnight', backupCount=14, encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter('%(message)s'))
    _logger.addHandler(file_handler)
except Exception:
    pass

def _log(event: str, **fields: object) -> None:
    try:
        payload = {"event": event}
        payload.update(fields)
        _logger.info(json.dumps(payload, separators=(",", ":")))
    except Exception:
        pass

def _state_log_fields(state: GameState) -> Dict[str, Any]:
    try:
        return {
            'width': state.board.width,
            'height': state.board.height,
            'grid': ''.join(state.board.grid),
            'p1': {'r': int(state.p1[0]), 'c': int(state.p1[1])},
            'p2': {'r': int(state.p2[0]), 'c': int(state.p2[1])},
            'collapsed': [{'r': int(r), 'c': int(c)} for (r, c) in state.collapsed],
            'collapsedCount': len(state.collapsed),
            'turn': int(state.turn),
        }
    except Exception:
        return {}

# In-memory game session tracker for summary logs
_GAMES: Dict[str, Dict[str, Any]] = {}

def _start_game(state: GameState) -> str:
    gid = str(uuid.uuid4())
    info: Dict[str, Any] = {
        'width': int(state.board.width),
        'height': int(state.board.height),
        'originalGrid': ''.join(state.board.grid),
        'moveHistory': [],  # list of [r,c,plies]
        'expectedWinner': None,
    }
    try:
        from game import solve_with_cache as _solve
        res = _solve(state, 'collapsi.db')
        info['expectedWinner'] = 1 if res.win else 2
    except Exception:
        info['expectedWinner'] = None
    _GAMES[gid] = info
    return gid

def _append_move(gid: str, move: Tuple[int, int], plies: Optional[int]) -> None:
    try:
        entry = [int(move[0]), int(move[1]), int(plies) if plies is not None else None]
        _GAMES.get(gid, {}).get('moveHistory', []).append(entry)
    except Exception:
        pass

def _log_summary(gid: str, final_state: GameState, actual_winner: Optional[int]) -> None:
    try:
        info = _GAMES.get(gid)
        if not info:
            return
        final_grid_pretty = final_state.board.pretty(final_state.p1, final_state.p2, set(final_state.collapsed))
        record = {
            'width': info.get('width'),
            'height': info.get('height'),
            'originalGrid': info.get('originalGrid'),
            'moveHistory': info.get('moveHistory'),
            'finalGrid': final_grid_pretty,
            'expectedWinner': info.get('expectedWinner'),
            'actualWinner': actual_winner,
        }
        _logger.info(json.dumps(record, separators=(",", ":")))
    except Exception:
        pass
    finally:
        try:
            _GAMES.pop(gid, None)
        except Exception:
            pass


@app.route('/')
def index() -> Any:
    """Serves the main HTML page of the game."""
    return send_from_directory('static', 'index.html')


@app.get('/api/logs/list')
def api_logs_list() -> Any:
    try:
        files = []
        for name in sorted(os.listdir(LOG_DIR)):
            path = os.path.join(LOG_DIR, name)
            if os.path.isfile(path):
                st = os.stat(path)
                files.append({
                    'name': name,
                    'size': st.st_size,
                    'mtime': int(st.st_mtime),
                })
        return jsonify({'ok': True, 'files': files})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.get('/api/logs/bundle')
def api_logs_bundle() -> Any:
    try:
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as z:
            for name in sorted(os.listdir(LOG_DIR)):
                path = os.path.join(LOG_DIR, name)
                if os.path.isfile(path):
                    z.write(path, arcname=name)
        mem.seek(0)
        return send_file(mem, mimetype='application/zip', as_attachment=True, download_name='collapsi-logs.zip')
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.post('/api/new')
def api_new() -> Any:
    """
    Starts a new game.
    Accepts a JSON body with optional 'size' and 'seed' parameters.
    Returns the initial game state, including which side the AI will play.
    """
    body = request.get_json(force=True, silent=True) or {}
    size = str(body.get('size', '4'))
    seed = body.get('seed', None)
    db_path = body.get('db', DEFAULT_DB)
    req_id = str(uuid.uuid4())
    if size == '3':
        board, p1, p2 = deal_board_3x3(seed=seed)
    else:
        board, p1, p2 = deal_board_4x4(seed=seed)
    ai_side = choose_ai_side_for_board(board, p1, p2, db_path)
    human_side = 2 if ai_side == 1 else 1
    state = GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=1)
    game_id = _start_game(state)
    _log("new_game", requestId=req_id, size=size, seed=seed, aiSide=ai_side, humanSide=human_side, state=_state_log_fields(state))
    return jsonify({
        'ok': True,
        'state': state_to_json(state, ai_side=ai_side, human_side=human_side),
        'legalMoves': legal_moves(state),
        'gameId': game_id,
    })


@app.post('/api/legal')
def api_legal() -> Any:
    """
    Calculates and returns the legal moves for the current player in a given game state.
    Accepts a JSON body with the current 'state'.
    """
    body = request.get_json(force=True)
    state = json_to_state(body['state'])
    return jsonify({'ok': True, 'legalMoves': legal_moves(state)})


@app.post('/api/move')
def api_move() -> Any:
    """
    Applies a player's move to the game state.
    Accepts a JSON body with the current 'state' and the 'move'.
    Returns the updated game state and the legal moves for the next player.
    """
    body = request.get_json(force=True)
    db_path = body.get('db', DEFAULT_DB)
    req_id = str(uuid.uuid4())
    state = json_to_state(body['state'])
    game_id = body.get('gameId')
    move = tuple(body['move'])  # type: ignore
    legal = legal_moves(state)
    if move not in legal:
        _log("illegal_move", requestId=req_id, state=_state_log_fields(state), move={'r': move[0], 'c': move[1]})
        return jsonify({'ok': False, 'error': 'Illegal move', 'legalMoves': legal}), 400
    path = find_example_path(state, move)
    # Append move with plies-left before applying
    try:
        from game import solve_with_cache as _solve
        res = _solve(state, body.get('db', DEFAULT_DB))
        if game_id:
            _append_move(game_id, move, res.plies)
    except Exception:
        pass
    next_state = apply_move(state, move)
    # Pre-cache the solution for the next player's turn to speed up AI response.
    solve_with_cache(next_state, db_path)
    _log("human_move", requestId=req_id, 
         fromState=_state_log_fields(state), toState=_state_log_fields(next_state), 
         move={'r': move[0], 'c': move[1]})
    return jsonify({
        'ok': True,
        'state': state_to_json(next_state),
        'legalMoves': legal_moves(next_state),
        'path': path,
        'gameId': game_id,
    })


@app.post('/api/ai')
def api_ai() -> Any:
    """
    Gets the AI's next move.
    Accepts a JSON body with the current 'state'.
    Returns the AI's chosen move, the updated game state, and legal moves for the human player.
    """
    body = request.get_json(force=True)
    db_path = body.get('db', DEFAULT_DB)
    req_id = str(uuid.uuid4())
    state = json_to_state(body['state'])
    game_id = body.get('gameId')

    # First attempt: perfect solver winning move (returns None if no forced win)
    move = ai_pick_move(state, db_path)

    # Legal moves for fallback strategies
    legal = legal_moves(state)
    if not legal:
        _log("ai_no_moves", requestId=req_id, state=_state_log_fields(state), winner=state.other_player())
        return jsonify({'ok': True, 'state': state_to_json(state), 'legalMoves': [], 'winner': state.other_player(), 'gameId': game_id})

    # If no forced win, choose best available using detailed per-move outcomes:
    # - Prefer any winning move with minimal plies
    # - Otherwise, choose the losing move that maximizes plies (delay)
    if move is None:
        detailed = solve_moves_cpp(state)  # must use native solver; no heuristic fallback
        if not detailed:
            return jsonify({'ok': False, 'error': 'C++ solver unavailable (no per-move data). Build and set COLLAPSI_CPP_EXE.'}), 500
        wins = [it for it in detailed if bool(it.get('win'))]
        def pl_val_min(it):
            pl = it.get('plies')
            return pl if isinstance(pl, int) else (10**9)
        def pl_val_max(it):
            pl = it.get('plies')
            return pl if isinstance(pl, int) else -1
        chosen = min(wins, key=pl_val_min) if wins else max(detailed, key=pl_val_max)
        mv = chosen.get('move') if isinstance(chosen, dict) else None
        if isinstance(mv, list) and len(mv) == 2:
            move = (int(mv[0]), int(mv[1]))
        if move is None:
            return jsonify({'ok': False, 'error': 'C++ solver failed to return a move.'}), 500

    # Safety: ensure selected move is legal
    if move not in legal:
        return jsonify({'ok': False, 'error': 'C++ solver suggested an illegal move', 'suggested': move, 'legalMoves': legal}), 500

    path = find_example_path(state, move)

    # Append AI move with plies-left before applying
    try:
        from game import solve_with_cache as _solve
        res = _solve(state, body.get('db', DEFAULT_DB))
        if game_id:
            _append_move(game_id, move, res.plies)
    except Exception:
        pass

    next_state = apply_move(state, move)
    solve_with_cache(next_state, db_path)

    try:
        from game import solve_with_cache as _solve
        # Log start and next state outcomes to detect suspicious contradictions
        start = _solve(state, db_path)
        after = _solve(next_state, db_path)
        _log("ai_move", requestId=req_id,
             fromState=_state_log_fields(state), toState=_state_log_fields(next_state),
             move={'r': move[0], 'c': move[1]}, startWin=start.win, startPlies=start.plies, nextHumanWin=after.win, nextPlies=after.plies)
        if start.win and after.win:
            _log("anomaly_win_flip", requestId=req_id, note="AI had win but moved into human win",
                 fromState=_state_log_fields(state), toState=_state_log_fields(next_state))
    except Exception:
        pass

    # If game concluded (opponent has no moves), log summary line and clear game session
    try:
        if game_id:
            nxt_legal = legal_moves(next_state)
            if not nxt_legal:
                actual_winner = state.turn  # mover wins when opponent has no replies
                _log_summary(game_id, next_state, actual_winner)
    except Exception:
        pass

    return jsonify({
        'ok': True,
        'move': move,
        'state': state_to_json(next_state),
        'legalMoves': legal_moves(next_state),
        'path': path,
        'gameId': game_id,
    })


@app.post('/api/solve')
def api_solve() -> Any:
    """
    Solves the game from the current state for the current player.
    Accepts a JSON body with the 'state'.
    Returns whether a win is possible and the best move if one exists.
    """
    body = request.get_json(force=True)
    db_path = body.get('db', DEFAULT_DB)
    state = json_to_state(body['state'])
    req_id = str(uuid.uuid4())
    res = solve_with_cache(state, db_path)
    _log("solve", requestId=req_id, state=_state_log_fields(state), win=res.win, best=res.best_move, plies=res.plies)
    return jsonify({
        'ok': True,
        'win': res.win,
        'best': res.best_move,
        'plies': res.plies,
        'normalized': (lambda: (lambda nb, p1, p2, col, dr, dc: {
            'board': board_to_json(nb),
            'p1': [p1[0], p1[1]],
            'p2': [p2[0], p2[1]],
            'collapsed': [[r, c] for (r, c) in col],
            'shift': {'dr': dr, 'dc': dc},
        })(*normalize_for_torus_view(state)))(),
    })


@app.post('/api/solve_moves')
def api_solve_moves() -> Any:
    """
    For the current state, computes perfect-play outcomes for each legal move.
    Returns an array of { move, win, plies }.
    """
    body = request.get_json(force=True)
    db_path = body.get('db', DEFAULT_DB)
    state = json_to_state(body['state'])
    moves = legal_moves(state)
    # Prefer C++ detailed output for per-move plies when available
    req_id = str(uuid.uuid4())
    detailed = solve_moves_cpp(state)
    if not detailed:
        return jsonify({'ok': False, 'error': 'C++ solver unavailable for per-move outcomes'}), 500
    _log("solve_moves", requestId=req_id, state=_state_log_fields(state), count=len(detailed))
    return jsonify({'ok': True, 'moves': detailed})


if __name__ == '__main__':
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '5000'))
    debug_env = os.getenv('FLASK_DEBUG', os.getenv('DEBUG', 'false')).lower()
    debug = debug_env in ('1', 'true', 'yes', 'on')
    # Ensure DB directory exists on startup if using a path with directories
    try:
        from game import _ensure_db_dir, _resolve_db_path
        # Resolve to a writable path and ensure the directory exists
        DEFAULT_RESOLVED = _resolve_db_path(DEFAULT_DB)
        _ensure_db_dir(DEFAULT_RESOLVED)
    except Exception:
        pass
    app.run(host=host, port=port, debug=debug)


