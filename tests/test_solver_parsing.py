import unittest
from unittest.mock import patch

from game import (
    Board,
    GameState,
    SolveResult,
    solve_with_cache,
    solve_moves_cpp,
    _state_to_cpp_arg,
    _decode_best_move_byte,
)


def _mk_4x4_all_a():
    grid = tuple(['A'] * 16)
    board = Board(width=4, height=4, grid=grid)
    s = GameState(board=board, collapsed=tuple(), p1=(0, 0), p2=(1, 1), turn=1)
    return board, s


class DummyProc:
    def __init__(self, out: str):
        self.stdout = out
        self.returncode = 0


class TestSolverParsing(unittest.TestCase):
    def test_given_cli_output_when_parsing_solve_with_cache_then_win_best_and_plies_correct(self):
        _, s = _mk_4x4_all_a()
        # Simulate CLI: "win best plies"
        with patch('game._find_cpp_exe', return_value='dummy'), \
             patch('game.subprocess.run', return_value=DummyProc("1 5 12\n")), \
             patch('game.db_store_state', lambda *a, **k: None):
            res = solve_with_cache(s, db_path=':memory:')
        self.assertIsInstance(res, SolveResult)
        self.assertTrue(res.win)
        self.assertEqual(res.best_move, (1, 1))  # 5 -> row=1,col=1
        self.assertEqual(res.plies, 12)

    def test_given_best_move_ff_when_parsing_solve_with_cache_then_best_is_none(self):
        _, s = _mk_4x4_all_a()
        with patch('game._find_cpp_exe', return_value='dummy'), \
             patch('game.subprocess.run', return_value=DummyProc("0 255 7\n")), \
             patch('game.db_store_state', lambda *a, **k: None):
            res = solve_with_cache(s, db_path=':memory:')
        self.assertFalse(res.win)
        self.assertIsNone(res.best_move)
        self.assertEqual(res.plies, 7)

    def test_given_malformed_cli_output_when_parsing_solve_with_cache_then_raises(self):
        _, s = _mk_4x4_all_a()
        with patch('game._find_cpp_exe', return_value='dummy'), \
             patch('game.subprocess.run', return_value=DummyProc("oops\n")), \
             patch('game.db_store_state', lambda *a, **k: None):
            with self.assertRaises(RuntimeError):
                solve_with_cache(s, db_path=':memory:')

    def test_given_per_move_tail_when_parsing_solve_moves_cpp_then_moves_and_plies_correct(self):
        _, s = _mk_4x4_all_a()
        # Tail format: "MM:PP:W" tokens; head can be anything with a '|'
        out = "1 0 0|05:12:1 03:7:0 invalid:tok\n"
        with patch('game._find_cpp_exe', return_value='dummy'), \
             patch('game.subprocess.run', return_value=DummyProc(out)):
            items = solve_moves_cpp(s)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['move'], [1, 1])  # 0x05 -> (1,1)
        self.assertTrue(items[0]['win'])
        self.assertEqual(items[0]['plies'], 12)
        self.assertEqual(items[1]['move'], [0, 3])  # 0x03 -> (0,3)
        self.assertFalse(items[1]['win'])
        self.assertEqual(items[1]['plies'], 7)

    def test_given_non_4x4_state_when_encoding_cpp_arg_then_raises(self):
        board = Board(width=3, height=3, grid=tuple(['A'] * 9))
        s = GameState(board=board, collapsed=tuple(), p1=(0, 0), p2=(1, 1), turn=1)
        with self.assertRaises(ValueError):
            _ = _state_to_cpp_arg(s)

    def test_given_all_a_board_when_encoding_cpp_arg_then_expected_format(self):
        board, s = _mk_4x4_all_a()
        arg = _state_to_cpp_arg(s)
        # For all 'A' board: a=0xFFFF, b2=b3=b4=0, X at (0,0)=0x0001, O at (1,1)=0x0020, c=0, turn=0
        self.assertEqual(arg, "ffff,0000,0000,0000,0001,0020,0000,0")

    def test_given_byte_value_when_decode_best_move_then_expected_coord_or_none(self):
        # 0xFF indicates no move
        self.assertIsNone(_decode_best_move_byte(0xFF))
        # Out of range -> None
        self.assertIsNone(_decode_best_move_byte(-1))
        self.assertIsNone(_decode_best_move_byte(256))
        # Valid values
        self.assertEqual(_decode_best_move_byte(0), (0, 0))
        self.assertEqual(_decode_best_move_byte(5), (1, 1))
        self.assertEqual(_decode_best_move_byte(15), (3, 3))


if __name__ == '__main__':
    unittest.main(verbosity=2)