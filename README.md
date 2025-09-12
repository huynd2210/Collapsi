Collapsi
========

AO* solver for Collapsi with SQLite caching and a simple Flask web UI.

Quickstart
----------

1) Python 3.10+
2) Install deps:
```
pip install -r requirements.txt
```
3) CLI solver (caches to SQLite):
```
python game.py --size 4 --db collapsi.db --seed 1
```
4) Web UI:
```
python app.py
# open http://127.0.0.1:5000
```


Reading solved_norm.db records
------------------------------

Binary artifacts
- solved_norm.db: append-only binary of normalized solved roots (key, turn, win, best, plies).
- norm_index.db (optional): compact overlay metadata to pretty-print a 4x4 board for a (key,turn) pair.

Record layout and semantics
- Current C++ writer struct (see [solve_norm_db.cpp](Collapsi/cpp/src/solve_norm_db.cpp)):
  ```cpp
  struct Record {
    uint64_t key;   // Szudzik+mix over bitboards including turn
    uint8_t  turn;  // 0 = X, 1 = O
    uint8_t  win;   // 0/1
    uint8_t  best;  // encoded move (see below), or 0xFF for none
    uint16_t plies; // depth-to-terminal under perfect play
    uint8_t  pad[4];// pad (record size and padding can vary by build)
  };
  ```
  Reference: [solve_norm_db.cpp](Collapsi/cpp/src/solve_norm_db.cpp:24)

- Field details:
  - key: 64-bit normalized root key (hash over bitboards + turn).
  - turn: who is to move (0=X, 1=O).
  - win: whether the side-to-move can force a win (0=no, 1=yes).
  - best: encoded best move byte, 0xFF means “no move”.
    - Encoding: upper nibble = from-index (0..15), lower nibble = to-index (0..15).
      - Example: decimal 18 = 0x12 → from=1, to=2.
      - Index to row/col (row-major): r = idx // 4, c = idx % 4.
      - Decoder: [read_records.decode_move()](Collapsi/tools/read_records.py:37)
    - Helpers in C++: [solver.encode_move()](Collapsi/cpp/include/solver.hpp:38), [solver.move_from()](Collapsi/cpp/include/solver.hpp:39), [solver.move_to()](Collapsi/cpp/include/solver.hpp:40)
  - plies: distance to terminal (≥1 when win==1; typically 0..50 on 4x4).

Reading records (CLI)
- Text format (first 5):
  ```
  python Collapsi/tools/read_records.py --db Collapsi/data/solved_norm.db --limit 5
  ```
- JSON format (first 5):
  ```
  python Collapsi/tools/read_records.py --db Collapsi/data/solved_norm.db --format json --limit 5
  ```
  Options are parsed in [read_records.build_arg_parser()](Collapsi/tools/read_records.py:304). Core streaming logic: [read_records.iter_solved_records](Collapsi/tools/read_records.py:156) with automatic layout detection: [read_records._detect_solved_record_format_from_path](Collapsi/tools/read_records.py:112).

Pretty board overlay (optional)
- If you have a matching norm_index.db:
  ```
  python Collapsi/tools/read_records.py --db Collapsi/data/solved_norm.db --index Collapsi/data/norm_index.db --board --limit 3
  ```
  Overlay loader: [read_records.load_norm_index](Collapsi/tools/read_records.py:229), renderer: [read_records.render_overlay_grid](Collapsi/tools/read_records.py:261).

Listing raw torus-shifted keys (optional)
- If you have norm2raw/*.txt available:
  ```
  python Collapsi/tools/read_records.py --db Collapsi/data/solved_norm.db --norm2raw Collapsi/cpp/data/norm2raw --raw-keys --limit 1
  ```
  Reader: [read_records.list_raw_keys_for](Collapsi/tools/read_records.py:285).

Validate entire DB (statistics and sanity checks)
- Stream all entries by default:
  ```
  python Collapsi/tools/validate_solved_db.py Collapsi/data/solved_norm.db
  ```
  Or cap:
  ```
  python Collapsi/tools/validate_solved_db.py Collapsi/data/solved_norm.db 500000
  ```
  Implementation: [validate_solved_db.py](Collapsi/tools/validate_solved_db.py). It reports:
  - count, turn distribution, win distribution
  - plies min/avg/max
  - bad_move_count (invalid best encoding)
  - anomaly_count (plies outside 0..50, or win==1 with plies&lt;1)
  - samples of first few and anomaly indices

Quick anomaly checks
- Zero keys in first K records:
  ```
  python Collapsi/tools/check_zero_keys.py Collapsi/data/solved_norm.db 1000
  ```
  Script: [check_zero_keys.py](Collapsi/tools/check_zero_keys.py).

Index-to-grid mapping (4×4)
- Indices 0..15 map row-major:
  - 0..3 = row 0, 4..7 = row 1, 8..11 = row 2, 12..15 = row 3
  - (r,c) = (idx // 4, idx % 4)

