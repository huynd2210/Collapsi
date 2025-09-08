#!/usr/bin/env bash
set -euo pipefail

# Collapsi local parallel solver runner (Linux/macOS)
# - Configures and builds native tools (solve_norm_db, collapsi_cpp)
# - Spawns N shard processes in parallel (one per CPU by default)
# - Merges and deduplicates the output into out/solved_norm.merged.db
#
# Usage:
#   ./tools/parallel_solve.sh [-s STRIDE] [-l LIMIT] [-b BATCH] [-o OUT_DIR]
#     -s STRIDE   Number of parallel shards (default: number of CPUs)
#     -l LIMIT    Max records per shard (default: 10000000)
#     -b BATCH    Flush batch size (default: 1000000)
#     -o OUT_DIR  Output directory (default: out)
#
# Environment variables (optional overrides):
#   STRIDE, LIMIT, BATCH, OUT
#
# Requires: cmake, a C++ toolchain, and optionally ninja (faster). Will fall back if ninja not found.

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${here}/.." && pwd)"
CPP_DIR="${REPO_ROOT}/Collapsi/cpp"
BUILD_DIR="${CPP_DIR}/build-ninja"
SOLVER_BIN="${BUILD_DIR}/solve_norm_db"
CPP_BIN="${BUILD_DIR}/collapsi_cpp"

cpu_count() {
  if command -v nproc >/dev/null 2>&1; then nproc; elif command -v sysctl >/dev/null 2>&1; then sysctl -n hw.ncpu; else echo 1; fi
}

usage() {
  grep '^# ' "$0" | cut -c3-
  exit 1
}

# Defaults
STRIDE_DEFAULT="$(cpu_count)"
LIMIT_DEFAULT="10000000"
BATCH_DEFAULT="1000000"
OUT_DEFAULT="out"

STRIDE="${STRIDE:-$STRIDE_DEFAULT}"
LIMIT="${LIMIT:-$LIMIT_DEFAULT}"
BATCH="${BATCH:-$BATCH_DEFAULT}"
OUT="${OUT:-$OUT_DEFAULT}"

# Parse flags
while getopts ":s:l:b:o:h" opt; do
  case "$opt" in
    s) STRIDE="$OPTARG" ;;
    l) LIMIT="$OPTARG" ;;
    b) BATCH="$OPTARG" ;;
    o) OUT="$OPTARG" ;;
    h) usage ;;
    \?) echo "Unknown option: -$OPTARG" >&2; usage ;;
    :)  echo "Option -$OPTARG requires an argument" >&2; usage ;;
  esac
done

mkdir -p "${OUT}"

echo "[parallel_solve] STRIDE=${STRIDE} LIMIT=${LIMIT} BATCH=${BATCH} OUT=${OUT}"
echo "[parallel_solve] Repo root: ${REPO_ROOT}"

# Configure and build
GEN=""
if command -v ninja >/dev/null 2>&1; then
  GEN="-G Ninja"
  echo "[parallel_solve] Using Ninja generator"
else
  echo "[parallel_solve] Ninja not found; using default CMake generator"
fi

echo "[parallel_solve] Configuring CMake..."
cmake -S "${CPP_DIR}" -B "${BUILD_DIR}" ${GEN} -DCMAKE_BUILD_TYPE=Release

echo "[parallel_solve] Building native tools..."
PAR_JOBS="$(cpu_count)"
cmake --build "${BUILD_DIR}" --target solve_norm_db -- -j "${PAR_JOBS}"
cmake --build "${BUILD_DIR}" --target collapsi_cpp -- -j "${PAR_JOBS}"

# Export for optional Python usage
export COLLAPSI_CPP_EXE="${CPP_BIN}"

# Launch shards
pids=()
echo "[parallel_solve] Launching shard processes..."
for (( i=0; i<STRIDE; i++ )); do
  OUT_FILE="${OUT}/solved_norm.offset${i}.stride${STRIDE}.db"
  "${SOLVER_BIN}" \
    --out "${OUT_FILE}" \
    --stride "${STRIDE}" \
    --offset "${i}" \
    --limit "${LIMIT}" \
    --batch "${BATCH}" &
  pids+=( "$!" )
  echo "  shard ${i}/${STRIDE} -> ${OUT_FILE} (pid=$!)"
done

# Wait for all
echo "[parallel_solve] Waiting for shards to complete..."
ret=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then
    ret=1
  fi
done
if [[ $ret -ne 0 ]]; then
  echo "[parallel_solve] One or more shards exited with error" >&2
  exit $ret
fi

# Merge and dedup
MERGED="${OUT}/solved_norm.merged.db"
echo "[parallel_solve] Merging shards into ${MERGED} ..."
# shellcheck disable=SC2046
cat $(ls "${OUT}/solved_norm.offset"*.db 2>/dev/null | sort) > "${MERGED}" || true

if [[ -s "${MERGED}" ]]; then
  echo "[parallel_solve] Deduplicating merged DB..."
  "${SOLVER_BIN}" --dedup "${MERGED}" || true
  echo "[parallel_solve] DONE. Merged at ${MERGED}"
else
  echo "[parallel_solve] No shard files found to merge in ${OUT}" >&2
  exit 2
fi