import unittest

from game import (
    Board,
    GameState,
    _shift_grid_str,
    _shift_coord,
    _state_key,
)


class TestNormalization(unittest.TestCase):
    def _mk_board(self, rows):
        h = len(rows)
        w = len(rows[0])
        flat = []
        for r in rows:
            assert len(r) == w
            flat.extend(r)
        return Board(width=w, height=h, grid=tuple(flat))

    def test_given_torus_shift_when_hashing_then_key_invariant(self):
        # All A grid (A includes J for steps); easy to reason about invariance
        rows = [
            ["A", "A", "A", "A"],
            ["A", "A", "A", "A"],
            ["A", "A", "A", "A"],
            ["A", "A", "A", "A"],
        ]
        board = self._mk_board(rows)
        # Pick positions and a collapse set
        p1 = (3, 1)
        p2 = (2, 0)
        collapsed = ((0, 0), (1, 2))
        s = GameState(board=board, collapsed=collapsed, p1=p1, p2=p2, turn=1)

        # Compute normalized key
        k0 = _state_key(s)

        # Shift by dr, dc to simulate an equivalent torus configuration
        w = board.width
        h = board.height
        for dr in range(h):
            for dc in range(w):
                grid_str = _shift_grid_str(board.grid, w, h, dr, dc)
                nb = Board(width=w, height=h, grid=tuple(grid_str))
                np1 = _shift_coord(p1, dr, dc, w, h)
                np2 = _shift_coord(p2, dr, dc, w, h)
                ncol = tuple(sorted(_shift_coord(c, dr, dc, w, h) for c in collapsed))
                s2 = GameState(board=nb, collapsed=ncol, p1=np1, p2=np2, turn=1)
                k2 = _state_key(s2)
                # Normalized keys should be identical across torus shifts
                self.assertEqual(k0, k2, f"Mismatch for shift dr={dr}, dc={dc}")

    def test_given_same_position_when_turn_differs_then_state_key_differs(self):
        # Same position but different side-to-move must have different key strings
        rows = [
            ["A", "A", "A", "A"],
            ["A", "A", "A", "A"],
            ["A", "A", "A", "A"],
            ["A", "A", "A", "A"],
        ]
        board = self._mk_board(rows)
        p1 = (0, 0)
        p2 = (1, 1)
        s1 = GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=1)
        s2 = GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=2)
        k1 = _state_key(s1)
        k2 = _state_key(s2)
        self.assertNotEqual(k1, k2)


if __name__ == "__main__":
    unittest.main(verbosity=2)