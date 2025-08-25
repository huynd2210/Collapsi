from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

from flask import Flask, request, jsonify, send_from_directory

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


@app.route('/')
def index() -> Any:
    """Serves the main HTML page of the game."""
    return send_from_directory('static', 'index.html')


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
    if size == '3':
        board, p1, p2 = deal_board_3x3(seed=seed)
    else:
        board, p1, p2 = deal_board_4x4(seed=seed)
    ai_side = choose_ai_side_for_board(board, p1, p2, db_path)
    human_side = 2 if ai_side == 1 else 1
    state = GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=1)
    return jsonify({
        'ok': True,
        'state': state_to_json(state, ai_side=ai_side, human_side=human_side),
        'legalMoves': legal_moves(state),
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
    state = json_to_state(body['state'])
    move = tuple(body['move'])  # type: ignore
    legal = legal_moves(state)
    if move not in legal:
        return jsonify({'ok': False, 'error': 'Illegal move', 'legalMoves': legal}), 400
    path = find_example_path(state, move)
    next_state = apply_move(state, move)
    # Pre-cache the solution for the next player's turn to speed up AI response.
    solve_with_cache(next_state, db_path)
    return jsonify({
        'ok': True,
        'state': state_to_json(next_state),
        'legalMoves': legal_moves(next_state),
        'path': path,
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
    state = json_to_state(body['state'])
    move = ai_pick_move(state, db_path)
    legal = legal_moves(state)
    if not legal:
        return jsonify({'ok': True, 'state': state_to_json(state), 'legalMoves': [], 'winner': state.other_player()})
    if move is None:
        # If no winning move is found, use a heuristic to pick the best available move.
        move = legal[0]
    path = find_example_path(state, move)
    next_state = apply_move(state, move)
    solve_with_cache(next_state, db_path)
    return jsonify({
        'ok': True,
        'move': move,
        'state': state_to_json(next_state),
        'legalMoves': legal_moves(next_state),
        'path': path,
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
    res = solve_with_cache(state, db_path)
    return jsonify({
        'ok': True,
        'win': res.win,
        'best': res.best_move,
    })


if __name__ == '__main__':
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '5000'))
    debug_env = os.getenv('FLASK_DEBUG', os.getenv('DEBUG', 'false')).lower()
    debug = debug_env in ('1', 'true', 'yes', 'on')
    # Ensure DB directory exists on startup if using a path with directories
    try:
        from game import _ensure_db_dir
        _ensure_db_dir(DEFAULT_DB)
    except Exception:
        pass
    app.run(host=host, port=port, debug=debug)


