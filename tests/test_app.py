import os
import json
import unittest

# Disable strict native solver requirement for tests before importing app
os.environ["COLLAPSI_REQUIRE_CPP"] = "false"

from app import app as flask_app  # noqa: E402
import app as app_mod             # noqa: E402
from game import SolveResult      # noqa: E402


def _stub_solve_with_cache(state, db_path, depth_cap=None):
    # Deterministic stub: no forced win, plies reported as 4
    return SolveResult(win=False, best_move=None, proof_moves=None, plies=4)


def _stub_solve_moves_cpp(state):
    # Deterministic stub: compute legal moves via imported function and wrap into solver-like list
    moves = app_mod.legal_moves(state)
    out = []
    for (r, c) in moves:
        out.append({"move": [int(r), int(c)], "win": False, "plies": 4})
    return out


def _stub_ai_pick_move(state, db_path):
    # Force /api/ai down the detailed-per-move path
    return None


def _stub_choose_ai_side_for_board(board, p1, p2, db_path):
    # Stable side for tests
    return 1


class TestFlaskAPI(unittest.TestCase):
    def setUp(self):
        # Monkeypatch app-level imported symbols so we don't need the native solver
        self._orig_choose = app_mod.choose_ai_side_for_board
        self._orig_solve = app_mod.solve_with_cache
        self._orig_ai = app_mod.ai_pick_move
        self._orig_moves = app_mod.solve_moves_cpp

        app_mod.choose_ai_side_for_board = _stub_choose_ai_side_for_board
        app_mod.solve_with_cache = _stub_solve_with_cache
        app_mod.ai_pick_move = _stub_ai_pick_move
        app_mod.solve_moves_cpp = _stub_solve_moves_cpp

        self.client = flask_app.test_client()

    def tearDown(self):
        # Restore originals
        app_mod.choose_ai_side_for_board = self._orig_choose
        app_mod.solve_with_cache = self._orig_solve
        app_mod.ai_pick_move = self._orig_ai
        app_mod.solve_moves_cpp = self._orig_moves

    def test_given_index_and_static_assets_when_requested_then_html_and_correct_mime(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Collapsi", r.data)

        rjs = self.client.get("/main.js")
        self.assertEqual(rjs.status_code, 200)
        self.assertIn("application/javascript", rjs.headers.get("Content-Type", ""))

        rcss = self.client.get("/styles.css")
        self.assertEqual(rcss.status_code, 200)
        self.assertIn("text/css", rcss.headers.get("Content-Type", ""))

    def test_given_new_game_when_posted_then_returns_state_and_legal_moves(self):
        payload = {"size": "4", "seed": 123}
        r = self.client.post("/api/new", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("state", data)
        self.assertIn("legalMoves", data)
        state = data["state"]

        r2 = self.client.post("/api/legal", data=json.dumps({"state": state}), content_type="application/json")
        self.assertEqual(r2.status_code, 200)
        d2 = r2.get_json()
        self.assertTrue(d2["ok"])
        self.assertIsInstance(d2["legalMoves"], list)

    def test_given_state_when_calling_solve_and_solve_moves_then_returns_plies_and_per_move_details(self):
        # Start a new game
        payload = {"size": "4", "seed": 123}
        r = self.client.post("/api/new", data=json.dumps(payload), content_type="application/json")
        state = r.get_json()["state"]

        # /api/solve (stubbed plies=4)
        r1 = self.client.post("/api/solve", data=json.dumps({"state": state}), content_type="application/json")
        self.assertEqual(r1.status_code, 200)
        d1 = r1.get_json()
        self.assertTrue(d1["ok"])
        self.assertIn("plies", d1)
        self.assertIsInstance(d1["plies"], int)

        # /api/solve_moves returns per-move details (stubbed)
        r2 = self.client.post("/api/solve_moves", data=json.dumps({"state": state}), content_type="application/json")
        self.assertEqual(r2.status_code, 200)
        d2 = r2.get_json()
        self.assertTrue(d2["ok"])
        self.assertIn("moves", d2)
        self.assertIsInstance(d2["moves"], list)
        if d2["moves"]:
            m0 = d2["moves"][0]
            self.assertIn("move", m0)
            self.assertIn("plies", m0)

    def test_given_after_human_move_when_ai_called_then_returns_state_and_legal_moves(self):
        # New game
        payload = {"size": "4", "seed": 7}
        r = self.client.post("/api/new", data=json.dumps(payload), content_type="application/json")
        d = r.get_json()
        state = d["state"]
        legal = d["legalMoves"]
        self.assertTrue(legal)
        mv = legal[0]

        # Human move
        r1 = self.client.post("/api/move", data=json.dumps({"state": state, "move": mv}), content_type="application/json")
        self.assertEqual(r1.status_code, 200)
        d1 = r1.get_json()
        self.assertTrue(d1["ok"])
        next_state = d1["state"]

        # AI move (uses stubbed per-move details)
        r2 = self.client.post("/api/ai", data=json.dumps({"state": next_state}), content_type="application/json")
        self.assertEqual(r2.status_code, 200)
        d2 = r2.get_json()
        self.assertTrue(d2["ok"])
        self.assertIn("state", d2)
        self.assertIn("legalMoves", d2)


if __name__ == "__main__":
    unittest.main(verbosity=2)