from __future__ import annotations

# Facade module that re-exports Collapsi core functionality.
# Kept for backward compatibility with the Flask app and tests.
# Single-responsibility modules live under collapsi_core/*.

# Keep subprocess import here so tests can patch game.subprocess.run
import subprocess  # noqa: F401

# Robust imports so this module works when executed as part of the Collapsi
# package or imported directly. Prefer relative, then absolute package, then legacy top-level.
try:
    from .collapsi_core.board import Board, Card, Coord  # type: ignore
    from .collapsi_core.state import GameState  # type: ignore
    from .collapsi_core.deal import deal_board_3x3, deal_board_4x4  # type: ignore
    from .collapsi_core.moves import (  # type: ignore
        card_steps,
        wrap_step,
        neighbors,
        enumerate_destinations,
        legal_moves,
        apply_move,
        find_example_path,
        opponent_move_count_after,
        choose_child_by_heuristic,
    )
    from .collapsi_core.ai import (  # type: ignore
        choose_ai_side_for_board,
        ai_pick_move,
    )
    from .collapsi_core.normalize import (  # type: ignore
        normalize_for_torus_view,
        _shift_coord,
        _shift_grid_str,
        _normalize_for_torus,
    )
    from .collapsi_core.hashkey import (  # type: ignore
        _state_key as _state_key,
        _raw_state_key as _raw_state_key,
    )
    from .collapsi_core.db import (  # type: ignore
        _ensure_db_dir,
        _resolve_db_path,
        db_lookup_state,
        db_store_state,
    )
    from .collapsi_core.solver_cli import (  # type: ignore
        SolveResult,
        _find_cpp_exe,
        _state_to_cpp_arg,
        _decode_best_move_byte,
        solve_with_cache_impl,
        solve_moves_cpp_impl,
    )
except Exception:
    try:
        from Collapsi.collapsi_core.board import Board, Card, Coord  # type: ignore
        from Collapsi.collapsi_core.state import GameState  # type: ignore
        from Collapsi.collapsi_core.deal import deal_board_3x3, deal_board_4x4  # type: ignore
        from Collapsi.collapsi_core.moves import (  # type: ignore
            card_steps,
            wrap_step,
            neighbors,
            enumerate_destinations,
            legal_moves,
            apply_move,
            find_example_path,
            opponent_move_count_after,
            choose_child_by_heuristic,
        )
        from Collapsi.collapsi_core.ai import (  # type: ignore
            choose_ai_side_for_board,
            ai_pick_move,
        )
        from Collapsi.collapsi_core.normalize import (  # type: ignore
            normalize_for_torus_view,
            _shift_coord,
            _shift_grid_str,
            _normalize_for_torus,
        )
        from Collapsi.collapsi_core.hashkey import (  # type: ignore
            _state_key as _state_key,
            _raw_state_key as _raw_state_key,
        )
        from Collapsi.collapsi_core.db import (  # type: ignore
            _ensure_db_dir,
            _resolve_db_path,
            db_lookup_state,
            db_store_state,
        )
        from Collapsi.collapsi_core.solver_cli import (  # type: ignore
            SolveResult,
            _find_cpp_exe,
            _state_to_cpp_arg,
            _decode_best_move_byte,
            solve_with_cache_impl,
            solve_moves_cpp_impl,
        )
    except Exception:
        from collapsi_core.board import Board, Card, Coord  # type: ignore
        from collapsi_core.state import GameState  # type: ignore
        from collapsi_core.deal import deal_board_3x3, deal_board_4x4  # type: ignore
        from collapsi_core.moves import (  # type: ignore
            card_steps,
            wrap_step,
            neighbors,
            enumerate_destinations,
            legal_moves,
            apply_move,
            find_example_path,
            opponent_move_count_after,
            choose_child_by_heuristic,
        )
        from collapsi_core.ai import (  # type: ignore
            choose_ai_side_for_board,
            ai_pick_move,
        )
        from collapsi_core.normalize import (  # type: ignore
            normalize_for_torus_view,
            _shift_coord,
            _shift_grid_str,
            _normalize_for_torus,
        )
        from collapsi_core.hashkey import (  # type: ignore
            _state_key as _state_key,
            _raw_state_key as _raw_state_key,
        )
        from collapsi_core.db import (  # type: ignore
            _ensure_db_dir,
            _resolve_db_path,
            db_lookup_state,
            db_store_state,
        )
        from collapsi_core.solver_cli import (  # type: ignore
            SolveResult,
            _find_cpp_exe,
            _state_to_cpp_arg,
            _decode_best_move_byte,
            solve_with_cache_impl,
            solve_moves_cpp_impl,
        )


def _run_proc_patchable(exe: str, arg: str) -> str:
    """Adapter using this module's subprocess for test patching."""
    proc = subprocess.run([exe, '--state', arg], capture_output=True, text=True, check=False)
    return (proc.stdout or '').strip()


def solve_with_cache(state: GameState, db_path: str, depth_cap: int | None = None) -> SolveResult:
    # Forward with patchable hooks so tests can stub game._find_cpp_exe / game.subprocess.run / game.db_store_state
    return solve_with_cache_impl(
        state,
        db_path,
        find_cpp_exe=_find_cpp_exe,
        run_proc=_run_proc_patchable,
        db_store=db_store_state,
    )


def solve_moves_cpp(state: GameState):
    # Forward with patchable hooks
    return solve_moves_cpp_impl(
        state,
        find_cpp_exe=_find_cpp_exe,
        run_proc=_run_proc_patchable,
    )


def aostar_solve(state: GameState, *args, **kwargs) -> SolveResult:
    """Deprecated shim preserved for compatibility."""
    return solve_with_cache(state, db_path=kwargs.get('db_path', 'collapsi.db'))


def main() -> None:
    # CLI driver delegated to collapsi_core.cli
    try:
        from .collapsi_core.cli import main as _main  # type: ignore
    except Exception:
        try:
            from Collapsi.collapsi_core.cli import main as _main  # type: ignore
        except Exception:
            from collapsi_core.cli import main as _main  # type: ignore
    _main()


if __name__ == '__main__':
    main()
