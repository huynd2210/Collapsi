import unittest

from game import (
    Board,
    GameState,
    card_steps,
    legal_moves,
    apply_move,
    aostar_solve,
    deal_board_3x3,
    find_example_path,
)


def make_board(rows):
    h = len(rows)
    w = len(rows[0])
    flat = []
    for r in rows:
        assert len(r) == w
        flat.extend(r)
    return Board(width=w, height=h, grid=tuple(flat))


class TestCollapsiBasics(unittest.TestCase):
    def test_card_steps_values(self):
        self.assertEqual(card_steps('J'), 1)
        self.assertEqual(card_steps('A'), 1)
        self.assertEqual(card_steps('2'), 2)
        self.assertEqual(card_steps('3'), 3)
        self.assertEqual(card_steps('4'), 4)

    def test_wrap_around_moves_from_corner(self):
        board = make_board([
            ['A', '2', '2', '2'],
            ['2', '2', '2', '2'],
            ['2', '2', '2', '2'],
            ['2', '2', '2', '2'],
        ])
        p1 = (0, 0)
        p2 = (1, 1)
        state = GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=1)
        moves = set(legal_moves(state))
        # Step=1 from (0,0): expect wrap to (0,3) and (3,0) available
        self.assertIn((0, 3), moves)
        self.assertIn((3, 0), moves)

    def test_cannot_end_on_opponent(self):
        board = make_board([
            ['A', '2', '2', '2'],
            ['2', '2', '2', '2'],
            ['2', '2', '2', '2'],
            ['2', '2', '2', '2'],
        ])
        p1 = (0, 1)
        p2 = (0, 0)  # opponent adjacent
        state = GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=1)
        moves = set(legal_moves(state))
        self.assertNotIn(p2, moves)

    def test_apply_move_collapses_and_switches_turn(self):
        board = make_board([
            ['A', '2', '2', '2'],
            ['2', '2', '2', '2'],
            ['2', '2', '2', '2'],
            ['2', '2', '2', '2'],
        ])
        start = (0, 0)
        p2 = (1, 1)
        state = GameState(board=board, collapsed=tuple(), p1=start, p2=p2, turn=1)
        # Move right by 1
        new_state = apply_move(state, (0, 1))
        self.assertEqual(new_state.turn, 2)
        self.assertIn(start, set(new_state.collapsed))
        self.assertEqual(new_state.p1, (0, 1))
        self.assertEqual(new_state.p2, p2)

    def test_legal_moves_blocked_by_collapsed(self):
        board = make_board([
            ['A', '2', '2', '2'],
            ['2', '2', '2', '2'],
            ['2', '2', '2', '2'],
            ['2', '2', '2', '2'],
        ])
        p1 = (0, 0)
        p2 = (2, 2)
        collapsed = {(0, 1), (1, 0), (3, 0), (0, 3)}  # all neighbors of p1
        state = GameState(board=board, collapsed=tuple(sorted(collapsed)), p1=p1, p2=p2, turn=1)
        self.assertEqual(legal_moves(state), [])


class TestAOSolver(unittest.TestCase):
    def test_forced_win_by_collapsing_opponent_last_neighbor(self):
        # Opponent at (0,0), their 1-step neighbors are mostly collapsed except our current cell (0,1).
        # After we move, our starting cell collapses, leaving opponent with zero moves.
        board = make_board([
            ['A', 'J', '2', '2'],
            ['2', '2', '2', '2'],
            ['2', '2', '2', '2'],
            ['2', '2', '2', '2'],
        ])
        p2 = (0, 0)  # opponent on 'A' -> 1 step
        p1 = (0, 1)  # us on 'J' -> 1 step
        pre_collapsed = {(1, 0), (3, 0), (0, 3)}  # all other neighbors of (0,0)
        state = GameState(board=board, collapsed=tuple(sorted(pre_collapsed)), p1=p1, p2=p2, turn=1)
        res = aostar_solve(state)
        self.assertTrue(res.win)
        # Any legal move that isn't onto the opponent should be acceptable
        allowed = set(legal_moves(state))
        allowed.discard(p2)
        self.assertIn(res.best_move, allowed)

    def test_no_moves_is_loss(self):
        board = make_board([
            ['A', '2', '2', '2'],
            ['2', '2', '2', '2'],
            ['2', '2', '2', '2'],
            ['2', '2', '2', '2'],
        ])
        p1 = (0, 0)
        p2 = (1, 1)
        collapsed = {(0, 1), (1, 0), (3, 0), (0, 3)}  # block all exits for p1
        state = GameState(board=board, collapsed=tuple(sorted(collapsed)), p1=p1, p2=p2, turn=1)
        res = aostar_solve(state)
        self.assertFalse(res.win)

    def test_3x3_deal_and_solve_runs(self):
        board, p1, p2 = deal_board_3x3(seed=42)
        # Validate counts: 2J, 4A, 3x'2'
        flat = list(board.grid)
        self.assertEqual(flat.count('J'), 2)
        self.assertEqual(flat.count('A'), 4)
        self.assertEqual(flat.count('2'), 3)
        state = GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=1)
        # Ensure the solver returns a boolean outcome and does not crash
        res = aostar_solve(state, depth_cap=12)
        self.assertIn(res.win, (True, False))

    def test_path_is_orthogonal(self):
        # Construct a small case where from (0,2) to (2,0) requires 2 orthogonal steps via wrap
        board = make_board([
            ['A', 'A', 'A'],
            ['A', '2', 'A'],
            ['A', 'A', 'A'],
        ])
        p1 = (0, 2)  # current
        p2 = (1, 1)
        state = GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=1)
        # card at (0,2) is 'A' -> 1 step, so cannot reach (2,0) in one move
        self.assertNotIn((2, 0), set(legal_moves(state)))
        # Simulate a '2' on starting cell to allow 2-step path
        board2 = make_board([
            ['A', 'A', '2'],
            ['A', '2', 'A'],
            ['A', 'A', 'A'],
        ])
        state2 = GameState(board=board2, collapsed=tuple(), p1=p1, p2=p2, turn=1)
        # With 2 steps, (2,0) should be reachable via orthogonal wrap path
        self.assertIn((2, 0), set(legal_moves(state2)))
        path = find_example_path(state2, (2, 0))
        self.assertIsNotNone(path)
        # Every consecutive pair should differ by manhattan distance 1 (orthogonal)
        for (r1, c1), (r2, c2) in zip(path, path[1:]):
            dr = (r2 - r1)
            dc = (c2 - c1)
            # account for wrap by normalizing to {-1,0,1}
            dr = max(-1, min(1, dr))
            dc = max(-1, min(1, dc))
            self.assertIn((abs(dr), abs(dc)), [(1, 0), (0, 1)])


if __name__ == '__main__':
    unittest.main()


