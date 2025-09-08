import os
import json
import tempfile
import unittest

# Disable strict native solver requirement for tests that import app
os.environ["COLLAPSI_REQUIRE_CPP"] = "false"

from app import board_to_json, board_from_json, state_to_json, json_to_state  # noqa: E402
from game import (  # noqa: E402
    Board,
    GameState,
    db_store_state,
    db_lookup_state,
    _state_key,
)


class TestDbAndJson(unittest.TestCase):
    def _mk_board(self, rows):
        h = len(rows)
        w = len(rows[0])
        flat = []
        for r in rows:
            assert len(r) == w
            flat.extend(r)
        return Board(width=w, height=h, grid=tuple(flat))

    def test_given_board_when_roundtrip_json_then_equal(self):
        rows = [
            ["A", "2", "3", "4"],
            ["J", "A", "2", "3"],
            ["4", "J", "A", "2"],
            ["3", "4", "J", "A"],
        ]
        board = self._mk_board(rows)
        bj = board_to_json(board)
        self.assertEqual(bj["width"], 4)
        self.assertEqual(bj["height"], 4)
        self.assertEqual(len(bj["grid"]), 16)

        back = board_from_json(bj)
        self.assertEqual(back.width, 4)
        self.assertEqual(back.height, 4)
        self.assertEqual(tuple(back.grid), tuple(board.grid))

        # Accepts non-str in grid and coerces to str
        bj2 = {"width": 2, "height": 2, "grid": [1, 2, 3, 4]}
        back2 = board_from_json(bj2)
        self.assertEqual(back2.grid, ("1", "2", "3", "4"))

    def test_given_state_when_roundtrip_json_then_equal(self):
        board = self._mk_board([
            ["A", "2", "3", "4"],
            ["J", "A", "2", "3"],
            ["4", "J", "A", "2"],
            ["3", "4", "J", "A"],
        ])
        s = GameState(board=board, collapsed=((0, 1), (2, 3)), p1=(1, 1), p2=(2, 2), turn=2)
        sj = state_to_json(s, ai_side=1, human_side=2)
        self.assertIn("board", sj)
        self.assertEqual(sj["turn"], 2)
        self.assertEqual(sj["aiSide"], 1)
        self.assertEqual(sj["humanSide"], 2)
        self.assertIn([0, 1], sj["collapsed"])

        s2 = json_to_state(sj)
        self.assertEqual(s2.turn, 2)
        self.assertEqual(s2.p1, (1, 1))
        self.assertEqual(s2.p2, (2, 2))
        self.assertIn((0, 1), s2.collapsed)
        self.assertIn((2, 3), s2.collapsed)

    def test_given_solved_state_when_store_then_lookup_returns_saved_values(self):
        # Use a temporary on-disk database path
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "collapsi.db")
            board = self._mk_board([
                ["A", "2", "3", "4"],
                ["J", "A", "2", "3"],
                ["4", "J", "A", "2"],
                ["3", "4", "J", "A"],
            ])
            s = GameState(board=board, collapsed=((1, 1),), p1=(0, 0), p2=(1, 2), turn=1)
            key = _state_key(s)
            db_store_state(db_path, s, win=True, best_move=(3, 3), plies=9)
            looked = db_lookup_state(db_path, key)
            self.assertIsNotNone(looked)
            assert looked is not None
            win, best, plies = looked
            self.assertTrue(win)
            self.assertEqual(best, (3, 3))
            self.assertEqual(plies, 9)

    def test_given_nested_path_when_store_state_then_directories_created_and_lookup_ok(self):
        with tempfile.TemporaryDirectory() as td:
            nested = os.path.join(td, "deep", "nest", "file.db")
            board = self._mk_board([
                ["A", "2", "3", "4"],
                ["J", "A", "2", "3"],
                ["4", "J", "A", "2"],
                ["3", "4", "J", "A"],
            ])
            s = GameState(board=board, collapsed=tuple(), p1=(0, 0), p2=(1, 1), turn=1)
            # Should not raise even though directories do not yet exist
            db_store_state(nested, s, win=False, best_move=None, plies=None)
            # Lookup by key should succeed with (False, None, None)
            key = _state_key(s)
            looked = db_lookup_state(nested, key)
            self.assertIsNotNone(looked)
            assert looked is not None
            win, best, plies = looked
            self.assertFalse(win)
            self.assertIsNone(best)
            self.assertIsNone(plies)


if __name__ == "__main__":
    unittest.main(verbosity=2)