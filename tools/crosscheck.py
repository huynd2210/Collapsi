import subprocess
import random
import time
from typing import Tuple
import sys
sys.path.append('.')
import game  # type: ignore

def run_py_on_state(board, p1, p2, turn=1) -> Tuple[bool, int]:
    state = game.GameState(board=board, collapsed=tuple(), p1=p1, p2=p2, turn=turn)
    t0 = time.time()
    res = game.aostar_solve(state)
    took = int((time.time() - t0) * 1000)
    return res.win, took

def run_cpp_state(a, b2, b3, b4, x, o, c, turn) -> Tuple[bool, int]:
    state_arg = f"{a:04x},{b2:04x},{b3:04x},{b4:04x},{x:04x},{o:04x},{c:04x},{turn:01x}"
    p = subprocess.run([r"cpp\\build\\Release\\collapsi_cpp.exe", "--state", state_arg], capture_output=True, text=True)
    out = p.stdout.strip().split()
    win = (out[0] == '1') if out else False
    us = 0
    if len(out) >= 3 and out[2].endswith('us'):
        try:
            us = int(out[2][:-2])
        except:  # noqa: E722
            us = 0
    return win, us // 1000

def main():
    random.seed(0)
    total = 10
    mismatches = 0
    for _ in range(total):
        seed = random.randrange(1_000_000)
        board, p1, p2 = game.deal_board_4x4(seed=seed)
        # Build bitboards (A includes J)
        a = b2 = b3 = b4 = 0
        for r in range(4):
            for c in range(4):
                idx = r * 4 + c
                card = board.at(r, c)
                if card in ('A', 'J'):
                    a |= (1 << idx)
                elif card == '2':
                    b2 |= (1 << idx)
                elif card == '3':
                    b3 |= (1 << idx)
                elif card == '4':
                    b4 |= (1 << idx)
        x = (1 << (p1[0] * 4 + p1[1]))
        o = (1 << (p2[0] * 4 + p2[1]))
        c = 0
        win_py, ms_py = run_py_on_state(board, p1, p2, turn=1)
        win_cpp, ms_cpp = run_cpp_state(a, b2, b3, b4, x, o, c, 0)  # C++ turn=0 means X to move
        print(f"seed={seed} py={win_py} ({ms_py}ms) cpp={win_cpp} ({ms_cpp}ms)")
        if win_py != win_cpp:
            mismatches += 1
    print(f"Checked {total} seeds, mismatches={mismatches}")

if __name__ == '__main__':
    main()


