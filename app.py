from __future__ import annotations

import json
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


DEFAULT_DB = 'collapsi.db'


def board_to_json(board: Board) -> Dict[str, Any]:
    return {
        'width': board.width,
        'height': board.height,
        'grid': list(board.grid),
    }


def board_from_json(data: Dict[str, Any]) -> Board:
    width = int(data['width'])
    height = int(data['height'])
    grid = tuple(str(x) for x in data['grid'])
    return Board(width=width, height=height, grid=grid)


def state_to_json(state: GameState, ai_side: int | None = None, human_side: int | None = None) -> Dict[str, Any]:
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
    board = board_from_json(data['board'])
    collapsed = tuple((int(r), int(c)) for r, c in data.get('collapsed', []))
    p1r, p1c = data['p1']
    p2r, p2c = data['p2']
    turn = int(data['turn'])
    return GameState(board=board, collapsed=collapsed, p1=(int(p1r), int(p1c)), p2=(int(p2r), int(p2c)), turn=turn)


app = Flask(__name__, static_url_path='', static_folder='static')


@app.route('/')
def index() -> Any:
    return send_from_directory('static', 'index.html')


@app.post('/api/new')
def api_new() -> Any:
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
    body = request.get_json(force=True)
    state = json_to_state(body['state'])
    return jsonify({'ok': True, 'legalMoves': legal_moves(state)})


@app.post('/api/move')
def api_move() -> Any:
    body = request.get_json(force=True)
    db_path = body.get('db', DEFAULT_DB)
    state = json_to_state(body['state'])
    move = tuple(body['move'])  # type: ignore
    legal = legal_moves(state)
    if move not in legal:
        return jsonify({'ok': False, 'error': 'Illegal move', 'legalMoves': legal}), 400
    path = find_example_path(state, move)
    next_state = apply_move(state, move)
    # Attempt to cache solve for next state's current player (optional)
    solve_with_cache(next_state, db_path)
    return jsonify({
        'ok': True,
        'state': state_to_json(next_state),
        'legalMoves': legal_moves(next_state),
        'path': path,
    })


@app.post('/api/ai')
def api_ai() -> Any:
    body = request.get_json(force=True)
    db_path = body.get('db', DEFAULT_DB)
    state = json_to_state(body['state'])
    move = ai_pick_move(state, db_path)
    legal = legal_moves(state)
    if not legal:
        return jsonify({'ok': True, 'state': state_to_json(state), 'legalMoves': [], 'winner': state.other_player()})
    if move is None:
        # pick heuristic fallback (first legal)
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


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)


