import os
import json
import unittest

# Disable strict native solver requirement for tests before importing app
os.environ["COLLAPSI_REQUIRE_CPP"] = "false"

from app import app as flask_app  # noqa: E402
from app import state_to_json     # noqa: E402
import app as app_mod             # noqa: E402
from game import (                # noqa: E402
    SolveResult,
    Board,
    GameState,
    neighbors,
)


def _stub_solve_with_cache(state, db_path, depth_cap=None):
    # Deterministic stub: no forced win, plies reported as 2
    return SolveResult(win=False, best_move=None, proof_moves=None, plies=2)


def _stub_ai_pick_move_none(state, db_path):
    # Force /api/ai down the detailed-per-move path (or early no-move exit)
    return None


def _stub_choose_ai_side_for_board(board, p1, p2, db_path):
    # Stable side for tests
    return 1


class TestFlaskAPIEdges(unittest.TestCase):
    def setUp(self):
        # Monkeypatch app-level imported symbols so we don't need the native solver
        self._orig_choose = app_mod.choose_ai_side_for_board
        self._orig_solve = app_mod.solve_with_cache
        self._orig_ai = app_mod.ai_pick_move
        self._orig_moves = app_mod.solve_moves_cpp

        app_mod.choose_ai_side_for_board = _stub_choose_ai_side_for_board
        app_mod.solve_with_cache = _stub_solve_with_cache
        app_mod.ai_pick_move = _stub_ai_pick_move_none
        # Do not define a default solve_moves_cpp here; individual tests will override as needed

        self.client = flask_app.test_client()

    def tearDown(self):
        # Restore originals
        app_mod.choose_ai_side_for_board = self._orig_choose
        app_mod.solve_with_cache = self._orig_solve
        app_mod.ai_pick_move = self._orig_ai
        app_mod.solve_moves_cpp = self._orig_moves

    def test_given_illegal_move_when_post_to_move_then_400_with_legal_moves(self):
        # Start a new game, then attempt an obviously illegal move
        payload = {"size": "4", "seed": 5}
        r = self.client.post("/api/new", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        state = r.get_json()["state"]

        illegal = [99, 99]
        r2 = self.client.post("/api/move", data=json.dumps({"state": state, "move": illegal}), content_type="application/json")
        self.assertEqual(r2.status_code, 400)
        d2 = r2.get_json()
        self.assertFalse(d2["ok"])
        self.assertIn("legalMoves", d2)
        self.assertIsInstance(d2["legalMoves"], list)

    def test_given_no_legal_moves_when_calling_ai_then_returns_winner(self):
        # Construct a 3x3 position with all 4 neighbors of P1 collapsed so no legal moves exist
        rows = [
            ["A", "A", "A"],
            ["A", "A", "A"],
            ["A", "A", "A"],
        ]
        board = Board(width=3, height=3, grid=tuple([c for row in rows for c in row]))
        p1 = (0, 0)
        p2 = (1, 1)
        col = tuple(sorted(neighbors(board, p1)))
        s = GameState(board=board, collapsed=col, p1=p1, p2=p2, turn=1)

        r = self.client.post("/api/ai", data=json.dumps({"state": state_to_json(s)}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["legalMoves"], [])
        # Since P1 has no moves, winner is the opponent (player 2)
        self.assertEqual(d["winner"], 2)

    def test_given_ai_suggests_illegal_move_when_calling_ai_then_500(self):
        # Override AI to suggest an illegal move
        orig_ai = app_mod.ai_pick_move
        app_mod.ai_pick_move = lambda state, db: (99, 99)
        try:
            payload = {"size": "4", "seed": 11}
            r = self.client.post("/api/new", data=json.dumps(payload), content_type="application/json")
            self.assertEqual(r.status_code, 200)
            state = r.get_json()["state"]

            r2 = self.client.post("/api/ai", data=json.dumps({"state": state}), content_type="application/json")
            self.assertEqual(r2.status_code, 500)
            d2 = r2.get_json()
            self.assertFalse(d2["ok"])
            self.assertIn("illegal move", d2["error"].lower())
        finally:
            app_mod.ai_pick_move = orig_ai

    def test_given_cpp_unavailable_when_calling_solve_moves_then_500(self):
        # Force /api/solve_moves to treat C++ per-move as unavailable
        app_mod.solve_moves_cpp = lambda state: []
        payload = {"size": "4", "seed": 3}
        r = self.client.post("/api/new", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        state = r.get_json()["state"]

        r2 = self.client.post("/api/solve_moves", data=json.dumps({"state": state}), content_type="application/json")
        self.assertEqual(r2.status_code, 500)
        d2 = r2.get_json()
        self.assertFalse(d2["ok"])
        self.assertIn("unavailable", d2["error"].lower())

    def test_given_logs_endpoints_then_list_and_bundle_work(self):
        # List logs
        r1 = self.client.get("/api/logs/list")
        self.assertEqual(r1.status_code, 200)
        d1 = r1.get_json()
        self.assertTrue(d1["ok"])
        self.assertIn("files", d1)
        self.assertIsInstance(d1["files"], list)

        # Bundle logs
        r2 = self.client.get("/api/logs/bundle")
        self.assertEqual(r2.status_code, 200)
        ctype = r2.headers.get("Content-Type", "")
        self.assertIn("application/zip", ctype)


if __name__ == "__main__":
    unittest.main(verbosity=2)