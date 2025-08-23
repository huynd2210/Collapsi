C++ Bitboard AO* Solver Plan
============================

Goal
----
Create a high-performance AO* solver in C++ using bitboards and bit operations. Keep existing Python solver; C++ is an optional, faster engine. The state should be encoded as compact bitsets and a Szudzik-paired hash. Output is a small record: turn, win, best_move (8-bit from/to).

Board Model (4x4)
-----------------
- 16 cells; use exactly 16-bit integers (uint16_t). No extras. One bit per cell.
- 6 piece bitboards (each uint16_t):
  - `bbA`: cells with A (1 step)
  - `bb2`: cells with 2 (2 steps)
  - `bb3`: cells with 3 (3 steps)
  - `bb4`: cells with 4 (4 steps)
  - `bbX`: cell of X
  - `bbO`: cell of O
- `bbCollapsed` (uint16_t): collapsed cells (impassable)

State Encoding
--------------
- turn: 1 bit (0 → X, 1 → O)
- win: 1 bit (0 → nobody/unknown, 1 → winner is player in `win_side` bit)
- best_move: 8 bits, 4 bits for from (0..15), 4 bits for to (0..15). 0xFF = none.
- board_hash: produced from the 7×16-bit bitboards. See “Hashing & Safety”.

Hashing & Safety (Experiments Required)
--------------------------------------
- We initially planned a “perfect hash” via recursive Szudzik pairing. With 16-bit inputs, the first pair peaks at ~2^32; a second pairing squares that to ~2^64; further pairings exceed 64 bits. Therefore, an exact perfect value for 7 pairings does not fit in 64 bits.
- Plan: use `unsigned __int128` to compute the recursive Szudzik value, then either:
  1) Keep a 128-bit key (two uint64_t) in the transposition table (recommended to avoid collisions), or
  2) Fold to 64-bit (e.g., xor-fold or SplitMix64) for speed/space, accepting negligible collision probability in practice.
- Action: implement a small experiment to confirm bit growth and choose default (we’ll default to 128-bit cache keys, with a compile-time option to fold to 64-bit).
  - We will still use only 16-bit bitboards for the board itself.

Move Generation
---------------
- Compute start index from `bbX` or `bbO` depending on turn. Look up steps from the card at that cell (A=1,2=2,3=3,4=4; X/O squares themselves are not cards; the card under a piece is the starting card/number).
- Enumerate all paths of exact length using DFS but with bitmasks:
  - Maintain `visitedMask` bitboard for the path.
  - For each step, compute neighbors using wrap: index arithmetic (r±1, c±1 mod 4). Avoid stepping into `bbCollapsed` and revisiting `visitedMask`.
  - Exclude finishing on opponent position.
  - Exclude finishing on starting cell.
  - Return set of destination indices.
- Complexity is small for 4x4; for speed, unroll neighbors, precompute neighbor indices for each cell.

Apply Move
----------
- Collapse starting cell bit in `bbCollapsed`.
- Move X or O bitboards accordingly.
- Switch turn.

AO* Search
----------
- Memoization keyed by `board_hash` + `turn` (pack into 65 bits, truncated to 64 via xor fold) for speed.
- Returns `win` (bool) and `best_move` (8-bit).
- For current player (OR node): iterate moves (ordered by heuristic: fewest opponent replies; prefer leaving exactly 1), choose a move that makes all opponent replies losing (AND condition). If such a move exists → win with that move; else losing.
- For opponent expansions use the same mechanism but role-inverted.

- `using bb_t = uint16_t;`
- `struct BitState { bb_t bbA, bb2, bb3, bb4, bbX, bbO, bbCollapsed; uint8_t turn; };`
- `struct Answer { bool win; uint8_t best_move; }; // best_move 0xFF = none`
- `struct CacheEntry { Answer ans; };`
- Cache key (configurable):
  - Default: 128-bit key as `struct Key128 { uint64_t hi, lo; };` with hasher.
  - Optional: 64-bit folded key via SplitMix64.
  - We also support packing the meta bits (turn) into the key.

Binary I/O & CLI
----------------
- No JSON. All I/O is binary- or hex-packed for space and speed.
  - CLI: `collapsi_cpp --solve --seed <n>` prints a single line: `<hash_hi>:<hash_lo> <turn_bit><win_bit><best_move_hex>` where `hash_hi` omitted if folding to 64-bit.
  - Add `--dump-state` to output seven 16-bit bitboards as hex for debugging only.
  - File storage (optional): fixed-size records with `{key(128 or 64), meta(1+1+8 bits packed)}`.
  - Later: C API bridge for Python.

Validation
----------
- Cross-check C++ answers on random seeds vs Python solver for consistency.
- Unit tests for: neighbor wrap, path enumeration, apply move, hashing stability, AO* outcomes.

Implementation Steps
--------------------
1) Scaffolding: `cpp/` folder with CMakeLists.txt; main files `bitboard.hpp/cpp`, `solver.hpp/cpp`, `hash.hpp/cpp`, `cli.cpp`.
2) Constants: neighbor tables for 4x4 (precompute 4 neighbors for 16 cells).
3) Encoding/decoding helpers for indices, masks, and moves.
4) Hash function via Szudzik, reduce to 64-bit.
5) Move gen using DFS with bitboards.
6) Apply move + turn switch and collapse.
7) AO* with memo and heuristic ordering.
8) CLI to run solve and print result/time.
9) Experiments: confirm bit growth of Szudzik recursion; collision checks by sampling random states.
10) Tests and a cross-check script vs Python.

Performance Targets
-------------------
- Goal: < 50 ms typical per position on 4x4 for random boards (with cache warm).
- Tight loops, inline small funcs, avoid heap in inner loops, reuse memory.

Open Questions / Assumptions
----------------------------
- Starting card: we assume the number under the current piece defines the step count each turn (as per rules). This implies X/O stand on card cells; their presence doesn’t remove card identity.
- For editor support later, we’ll need a compact import/export from the JS state to 7 bitboards.


