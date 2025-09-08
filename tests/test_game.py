import unittest

from game import (
    Board,
    GameState,
    card_steps,
    legal_moves,
    apply_move,
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
    def test_given_card_letters_when_querying_steps_then_expected_values(self):
        self.assertEqual(card_steps('J'), 1)
        self.assertEqual(card_steps('A'), 1)
        self.assertEqual(card_steps('2'), 2)
        self.assertEqual(card_steps('3'), 3)
        self.assertEqual(card_steps('4'), 4)

    def test_given_corner_a_when_stepping_one_then_wraparound_moves_exist(self):
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

    def test_given_adjacent_opponent_when_generating_moves_then_opponent_square_excluded(self):
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

    def test_given_start_state_when_apply_move_then_collapses_and_turn_switches(self):
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

    def test_given_blocked_neighbors_when_generating_moves_then_no_moves(self):
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
    def test_given_seed_when_deal_3x3_then_deck_distribution_valid(self):
        board, p1, p2 = deal_board_3x3(seed=42)
        flat = list(board.grid)
        self.assertEqual(flat.count('J'), 2)
        self.assertEqual(flat.count('A'), 4)
        self.assertEqual(flat.count('2'), 3)

    def test_given_two_step_path_when_find_example_path_then_moves_are_orthogonal(self):
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


