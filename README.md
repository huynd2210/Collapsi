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

Dev
---

- Run tests:
```
python -m pytest -q
```
- 3x3 deal uses 2xJ, 4xA, 3x2 to fit 9 cells.
- DB cache defaults to `collapsi.db`.

Notes
-----

- Movement is orthogonal with wrap-around, no revisiting cells during a move, cannot end on start or opponent, and collapsed cells are impassable.
- Heuristic: prefer moves that leave opponent with exactly 1 reply; else by fewest replies.


