from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Reuse helpers to estimate record sizes/counts
from .solved_reader import detect_record_format as _detect_solved_format  # [python.def detect_record_format()](Collapsi/collapsi_core/solved_reader.py:62)
from .solved_reader import _detect_index_format as _detect_index_format    # [python.def _detect_index_format()](Collapsi/collapsi_core/solved_reader.py:142)


@dataclass
class IndexJob:
    pids: List[int]
    exe: str
    db: str
    index_path: str
    stride: int
    started_at: float


def _data_dir() -> str:
    # Use repo-local data directory by default
    return os.path.join(os.getcwd(), "data")


def _job_state_path() -> str:
    return os.path.join(_data_dir(), "index_job.json")


def _ensure_dir(p: str) -> None:
    d = os.path.dirname(p)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def _builder_candidates() -> List[str]:
    # Try environment override first
    cand: List[str] = []
    env = os.getenv("COLLAPSI_INDEX_BUILDER_EXE")
    if env:
        cand.append(env)
    # Common local build outputs (Windows/MSVC, Ninja, and generic)
    # Support both repo-rooted "cpp/*" and namespaced "Collapsi/cpp/*" layouts.
    cand.extend([
        # Visual Studio/MSVC default build dir
        os.path.join("cpp", "build", "Release", "gen_index.exe"),
        os.path.join("cpp", "build", "Debug", "gen_index.exe"),
        os.path.join("cpp", "build", "gen_index"),  # MinGW or POSIX
        os.path.join("Collapsi", "cpp", "build", "Release", "gen_index.exe"),
        os.path.join("Collapsi", "cpp", "build", "Debug", "gen_index.exe"),
        os.path.join("Collapsi", "cpp", "build", "gen_index"),
        # Ninja build dir we use in scripts
        os.path.join("cpp", "build-ninja", "gen_index"),
        os.path.join("cpp", "build-ninja", "gen_index.exe"),
        os.path.join("Collapsi", "cpp", "build-ninja", "gen_index"),
        os.path.join("Collapsi", "cpp", "build-ninja", "gen_index.exe"),
        # Optional bin drop
        os.path.join("cpp", "bin", "gen_index.exe"),
        os.path.join("cpp", "bin", "gen_index"),
        os.path.join("Collapsi", "cpp", "bin", "gen_index.exe"),
        os.path.join("Collapsi", "cpp", "bin", "gen_index"),
        # PATH
        "gen_index",
    ])
    return cand


def _find_builder_exe() -> Optional[str]:
    for p in _builder_candidates():
        if os.path.isabs(p):
            if os.path.isfile(p):
                return p
        else:
            abs_p = os.path.join(os.getcwd(), p)
            if os.path.isfile(abs_p):
                return abs_p
    # Try which in PATH
    try:
        import shutil
        exe = shutil.which("gen_index")
        if exe:
            return exe
    except Exception:
        pass
    return None


def _read_job() -> Optional[IndexJob]:
    try:
        with open(_job_state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return IndexJob(
            pids=list(map(int, data.get("pids", []) or [])),
            exe=str(data.get("exe", "")),
            db=str(data.get("db", "")),
            index_path=str(data.get("index", "")),
            stride=int(data.get("stride", 1)),
            started_at=float(data.get("startedAt", 0.0)),
        )
    except Exception:
        return None


def _write_job(job: IndexJob) -> None:
    _ensure_dir(_job_state_path())
    with open(_job_state_path(), "w", encoding="utf-8") as f:
        json.dump({
            "pids": job.pids,
            "exe": job.exe,
            "db": job.db,
            "index": job.index_path,
            "stride": job.stride,
            "startedAt": job.started_at,
        }, f)


def _is_proc_running(pid: int) -> bool:
    try:
        # Cross-platform "is running" check
        if sys.platform.startswith("win"):
            # On Windows, os.kill with signal 0 doesn't exist. Use OpenProcess via ctypes is overkill.
            # Fallback: tasklist check
            import subprocess as sp
            out = sp.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
            return str(pid) in out.stdout
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def _clean_dead(job: IndexJob) -> IndexJob:
    live = [pid for pid in job.pids if _is_proc_running(pid)]
    if len(live) != len(job.pids):
        job = IndexJob(
            pids=live,
            exe=job.exe,
            db=job.db,
            index_path=job.index_path,
            stride=job.stride,
            started_at=job.started_at,
        )
        _write_job(job)
    return job


def estimate_db_records(db_path: str) -> Optional[int]:
    try:
        fmt, _ = _detect_solved_format(db_path)
        rec_sz = __import__("struct").calcsize(fmt)
        size = os.path.getsize(db_path)
        if rec_sz > 0:
            return size // rec_sz
    except Exception:
        pass
    return None


def current_index_stats(index_path: str) -> Dict[str, Optional[int]]:
    try:
        size = os.path.getsize(index_path)
    except Exception:
        return {"bytes": None, "records": None, "recSize": None}
    try:
        fmt, rec_sz = _detect_index_format(size)
        # Recompute rec_sz from fmt to be safe
        rec_sz = __import__("struct").calcsize(fmt)
    except Exception:
        rec_sz = 24
    recs = (size // rec_sz) if rec_sz > 0 else None
    return {"bytes": size, "records": recs, "recSize": rec_sz}


def ensure_index_async(db_path: str, index_path: str, stride: Optional[int] = None) -> Dict[str, object]:
    """
    Ensure an index build is running or completed. If index_path already exists and is non-empty, return status.
    Otherwise try to spawn the C++ generator (gen_index) in the background. Persist PID(s) to data/index_job.json.
    """
    _ensure_dir(index_path)
    # If index exists and has at least one record, consider it available
    stat = current_index_stats(index_path)
    if stat.get("records") not in (None, 0):
        return {"started": False, "available": True, "status": stat}

    # If a job is already running, return its status
    job = _read_job()
    if job and job.index_path == index_path and job.db == db_path:
        job = _clean_dead(job)
        if job.pids:
            return {"started": False, "available": False, "job": {"pids": job.pids, "exe": job.exe}, "status": stat}

    exe = _find_builder_exe()
    if not exe:
        # Cannot build: tool not available
        return {"started": False, "available": False, "error": "gen_index executable not found. Build C++ tools.", "status": stat}

    # Determine stride (parallel workers). Default to 1 unless overridden.
    try:
        env_stride = os.getenv("COLLAPSI_INDEX_BUILDER_STRIDE")
        if stride is None:
            stride = int(env_stride) if env_stride else 1
        stride = max(1, int(stride))
    except Exception:
        stride = 1

    # Optionally shard by stride/offset. For now, launch a single shard (offset 0) unless stride>1
    pids: List[int] = []
    for offset in range(stride):
        args = [
            exe,
            "--db", db_path,
            "--out", index_path,
            "--stride", str(stride),
            "--offset", str(offset),
        ]
        # Detach process
        creationflags = 0
        start_new_session = False
        if sys.platform.startswith("win"):
            # 0x00000008 = DETACHED_PROCESS
            creationflags = 0x00000008
        else:
            start_new_session = True
        try:
            proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=creationflags, start_new_session=start_new_session)
            pids.append(proc.pid)
        except Exception as e:
            # If any shard fails to start, continue with others
            continue

    if not pids:
        return {"started": False, "available": False, "error": "Failed to start gen_index", "status": stat}

    job = IndexJob(pids=pids, exe=exe, db=db_path, index_path=index_path, stride=stride, started_at=time.time())
    _write_job(job)

    return {"started": True, "available": False, "job": {"pids": pids, "exe": exe}, "status": stat}


def index_status(db_path: str, index_path: str) -> Dict[str, object]:
    stat = current_index_stats(index_path)
    total = estimate_db_records(db_path)
    job = _read_job()
    job_info = None
    running = False
    if job and job.index_path == index_path and job.db == db_path:
        job = _clean_dead(job)
        job_info = {"pids": job.pids, "exe": job.exe, "stride": job.stride, "startedAt": job.started_at}
        running = bool(job.pids)

    return {
        "ok": True,
        "running": running,
        "job": job_info,
        "index": stat,
        "dbTotalRecords": total,
    }