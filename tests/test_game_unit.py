import unittest
from game import (
    Board,
    GameState,
    card_steps,
    wrap_step,
    neighbors,
    enumerate_destinations,
    legal_moves,
    apply_move,
    find_example_path,
)


class TestGameUnit(unittest.TestCase):
    def _mk_board(self, rows):
        h = len(rows)
        w = len(rows[0])
        flat = []
        for r in rows:
            assert len(r) == w
            flat.extend(r)
        return Board(width=w, height=h, grid=tuple(flat))

    def test_given_board_with_torus_when_accessing_cells_then_indices_and_wraparound_correct(self):
        rows = [
            ['A', '2', '3'],
            ['4', 'J', 'A'],
            ['2', '3', '4'],
        ]
        board = self._mk_board(rows)
        self.assertEqual(board.index(1, 2), 5)
        self.assertEqual(board.at(-1, -1), '4')  # wraps to (2,2)
        self.assertEqual(board.at(3, 3), 'A')    # wraps to (0,0)

    def test_given_board_and_players_when_pretty_then_symbols_rendered(self):
        board = self._mk_board([
            ['A', 'A', 'A'],
            ['A', 'A', 'A'],
            ['A', 'A', 'A'],
        ])
        # p1 and p2 on same cell -> '*', collapsed shown as '·'
        txt = board.pretty((0, 0), (0, 0), {(1, 1), (2, 2)})
        self.assertIn('*', txt)
        self.assertIn('·', txt)
        # Distinct players show 'X' and 'O'
        txt2 = board.pretty((0, 1), (0, 2), {(1, 1)})
        self.assertIn('X', txt2)
        self.assertIn('O', txt2)
        self.assertNotIn('*', txt2)

    def test_given_card_letters_when_querying_steps_then_expected_values(self):
        self.assertEqual(card_steps('J'), 1)
        self.assertEqual(card_steps('A'), 1)
        self.assertEqual(card_steps('2'), 2)
        self.assertEqual(card_steps('3'), 3)
        self.assertEqual(card_steps('4'), 4)
        with self.assertRaises(ValueError):
            _ = card_steps('Z')  # invalid

    def test_given_coords_when_wrapping_and_finding_neighbors_then_expected_results(self):
        board = self._mk_board([
            ['A', 'A', 'A'],
            ['A', 'A', 'A'],
            ['A', 'A', 'A'],
        ])
        self.assertEqual(wrap_step(board, -1, -1), (2, 2))
        self.assertEqual(wrap_step(board, 3, 3), (0, 0))
        neigh = set(neighbors(board, (0, 0)))
        self.assertEqual(neigh, {(2, 0), (1, 0), (0, 2), (0, 1)})

    def test_given_state_when_enumerating_destinations_then_respects_blocks_and_rules(self):
        board = self._mk_board([
            ['A', 'A', 'A'],
            ['A', 'A', 'A'],
            ['A', 'A', 'A'],
        ])
        s = GameState(board=board, collapsed=tuple(), p1=(1, 1), p2=(2, 2), turn=1)
        dests = enumerate_destinations(s, start=(1, 1), steps=2, opponent=(2, 2))
        self.assertNotIn((1, 1), dests)  # cannot end on start
        self.assertNotIn((2, 2), dests)  # cannot end on opponent
        # Expect at least 7 destinations on 3x3 torus from center with 2 steps (excluding opponent)
        self.assertGreaterEqual(len(dests), 7)
        # Sample expected endpoints
        for expected in [(2, 1), (0, 1), (1, 0), (1, 2), (0, 0), (0, 2), (2, 0)]:
            if expected != (2, 2):
                self.assertIn(expected, dests)

        # Block all immediate neighbors: no path of length 2
        blocked = tuple(sorted(neighbors(board, (1, 1))))
        s2 = GameState(board=board, collapsed=blocked, p1=(1, 1), p2=(0, 0), turn=1)
        dests2 = enumerate_destinations(s2, start=(1, 1), steps=2, opponent=(0, 0))
        self.assertEqual(dests2, set())

    def test_given_state_when_apply_move_then_turn_switches_and_collapse_updates(self):
        board = self._mk_board([
            ['A', 'A', 'A'],
            ['A', 'A', 'A'],
            ['A', 'A', 'A'],
        ])
        s = GameState(board=board, collapsed=tuple(), p1=(0, 0), p2=(1, 1), turn=1)
        legal = set(legal_moves(s))
        self.assertEqual(legal, {(2, 0), (1, 0), (0, 2), (0, 1)})
        dest = (0, 1)
        ns = apply_move(s, dest)
        self.assertEqual(ns.turn, 2)
        self.assertEqual(ns.p1, dest)
        self.assertEqual(ns.p2, s.p2)
        self.assertIn((0, 0), set(ns.collapsed))

        # Now p2 moves
        s2 = GameState(board=board, collapsed=tuple(), p1=(0, 0), p2=(1, 1), turn=2)
        dest2 = (1, 0)
        ns2 = apply_move(s2, dest2)
        self.assertEqual(ns2.turn, 1)
        self.assertEqual(ns2.p2, dest2)
        self.assertIn((1, 1), set(ns2.collapsed))

    def test_given_state_and_dest_when_find_example_path_then_success_or_none_on_invalid(self):
        # Place '2' at (0,0) so steps = 2
        rows = [
            ['2', 'A', 'A'],
            ['A', 'A', 'A'],
            ['A', 'A', 'A'],
        ]
        board = self._mk_board(rows)
        s = GameState(board=board, collapsed=tuple(), p1=(0, 0), p2=(2, 2), turn=1)
        dest = (1, 1)
        path = find_example_path(s, dest)
        self.assertIsNotNone(path)
        assert path is not None
        self.assertEqual(path[0], (0, 0))
        self.assertEqual(path[-1], dest)
        self.assertEqual(len(path), 3)  # steps + 1

        # Destination equal to opponent is invalid
        s_bad = GameState(board=board, collapsed=tuple(), p1=(0, 0), p2=(0, 1), turn=1)
        path_bad = find_example_path(s_bad, (0, 1))
        self.assertIsNone(path_bad)

    def test_given_gamestate_when_calling_helpers_then_expected_values(self):
        board = self._mk_board([
            ['A', 'A', 'A'],
            ['A', 'A', 'A'],
            ['A', 'A', 'A'],
        ])
        s = GameState(board=board, collapsed=((1, 2),), p1=(0, 0), p2=(1, 1), turn=1)
        self.assertTrue(s.is_collapsed((1, 2)))
        self.assertEqual(s.other_player(), 2)
        self.assertEqual(s.player_pos(1), (0, 0))
        self.assertEqual(s.player_pos(2), (1, 1))
        s2 = s.with_turn(2)
        self.assertEqual(s2.turn, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)