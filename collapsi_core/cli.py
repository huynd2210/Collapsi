from __future__ import annotations

import argparse
from typing import Set

from .deal import deal_board_3x3, deal_board_4x4
from .state import GameState
from .moves import legal_moves, apply_move, find_example_path
from .ai import choose_ai_side_for_board, ai_pick_move
from .solver_cli import solve_with_cache_impl, solve_moves_cpp_impl


def main() -> None:
    parser = argparse.ArgumentParser(description='Collapsi solver and DB-backed AI')
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
        res = solve_with_cache_impl(state, args.db)
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

    def prompt_human_move(s: GameState):
        moves = legal_moves(s)
        if not moves:
            raise RuntimeError('No legal moves available')
        print('Your legal moves:', moves)
        while True:
            text = input('Enter your move as r,c or r c: ').strip()
            sep = ',' if ',' in text else ' '
            try:
                r_s, c_s = [t for t in text.split(sep) if t != '']
                move = (int(r_s), int(c_s))
            except Exception:
                print('Could not parse. Try again.')
                continue
            if move in moves:
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
                detailed = solve_moves_cpp_impl(state)
                if not detailed:
                    print("error: C++ solver unavailable; cannot choose a move.")
                    return
                wins = [it for it in detailed if bool(it.get('win'))]

                def _pl_min(it):
                    pl = it.get('plies')
                    return pl if isinstance(pl, int) else (10**9)

                def _pl_max(it):
                    pl = it.get('plies')
                    return pl if isinstance(pl, int) else -1

                chosen = min(wins, key=_pl_min) if wins else max(detailed, key=_pl_max)
                mv = chosen.get('move') if isinstance(chosen, dict) else None
                if isinstance(mv, list) and len(mv) == 2:
                    move = (int(mv[0]), int(mv[1]))
                if move is None:
                    print("error: C++ solver failed to return a move.")
                    return
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