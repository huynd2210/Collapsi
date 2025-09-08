#!/usr/bin/env bash
set -euo pipefail

# Configuration via environment variables:
#   BUCKET      (required)  GCS bucket name (no gs:// prefix), e.g. my-collapsi-bucket
#   PREFIX      (optional)  Object prefix in bucket, default: collapsi/solved_norm
#   STRIDE      (optional)  Shard stride, default: 1
#   OFFSET      (optional)  Shard offset in [0..STRIDE-1], default: 0
#   LIMIT       (optional)  Max records to produce, default: 10000000
#   BATCH       (optional)  Flush batch size, default: 1000000
#   SEEN_URIS   (optional)  Comma-separated gs:// paths to preload "seen" before run
#   DUMP_DIR    (optional)  If set, dump solved trees to this local dir for diagnostics
#   CPP_EXE     (optional)  Override CLI path. Defaults to /opt/collapsi/collapsi_cpp
#
# Behavior:
# - Resumes from existing shard object in GCS if present.
# - Runs solve_norm_db with the configured sharding.
# - Uploads/updates the shard object to GCS on completion.

: "${BUCKET:?Environment variable BUCKET is required}"
PREFIX="${PREFIX:-collapsi/solved_norm}"
STRIDE="${STRIDE:-${CLOUD_RUN_TASK_COUNT:-1}}"
OFFSET="${OFFSET:-${BATCH_TASK_INDEX:-${CLOUD_RUN_TASK_INDEX:-0}}}"
LIMIT="${LIMIT:-10000000}"
BATCH="${BATCH:-1000000}"
SEEN_URIS="${SEEN_URIS:-}"
DUMP_DIR="${DUMP_DIR:-}"
CPP_EXE="${CPP_EXE:-/opt/collapsi/solve_norm_db}"

export COLLAPSI_CPP_EXE="/opt/collapsi/collapsi_cpp"
export CLOUDSDK_CORE_DISABLE_PROMPTS=1

echo "[entrypoint] BUCKET=${BUCKET} PREFIX=${PREFIX} STRIDE=${STRIDE} OFFSET=${OFFSET} LIMIT=${LIMIT} BATCH=${BATCH}"
echo "[entrypoint] Using CLI: ${CPP_EXE}"

WORK=/opt/collapsi/work
OUT_DIR="${WORK}/out"
SEEN_DIR="${WORK}/seen"
mkdir -p "${OUT_DIR}" "${SEEN_DIR}"
if [[ -n "${DUMP_DIR}" ]]; then
  mkdir -p "${DUMP_DIR}"
fi

OUT_NAME="solved_norm.offset${OFFSET}.stride${STRIDE}.db"
OUT_LOCAL="${OUT_DIR}/${OUT_NAME}"
OUT_GS="gs://${BUCKET}/${PREFIX}/${OUT_NAME}"

# Resume existing shard from GCS if available
echo "[entrypoint] Checking GCS for existing shard: ${OUT_GS}"
if gsutil -q stat "${OUT_GS}"; then
  echo "[entrypoint] Found existing shard. Downloading to resume..."
  gsutil -q cp "${OUT_GS}" "${OUT_LOCAL}"
  ls -l "${OUT_LOCAL}" || true
else
  echo "[entrypoint] No existing shard found. Starting fresh."
fi

# Preload seen set(s) if provided
SEEN_ARGS=()
if [[ -n "${SEEN_URIS}" ]]; then
  IFS=',' read -r -a SEEN_LIST <<< "${SEEN_URIS}"
  for uri in "${SEEN_LIST[@]}"; do
    base="$(basename "${uri}")"
    dest="${SEEN_DIR}/${base}"
    echo "[entrypoint] Downloading seen DB: ${uri} -> ${dest}"
    gsutil -q cp "${uri}" "${dest}"
    SEEN_ARGS+=(--seen "${dest}")
  done
fi

# Build argument vector for solver
SOLVE_ARGS=(--out "${OUT_LOCAL}" --stride "${STRIDE}" --offset "${OFFSET}" --limit "${LIMIT}" --batch "${BATCH}")
if [[ -n "${DUMP_DIR}" ]]; then
  SOLVE_ARGS+=(--dumpdir "${DUMP_DIR}")
fi
if [[ ${#SEEN_ARGS[@]} -gt 0 ]]; then
  SOLVE_ARGS+=("${SEEN_ARGS[@]}")
fi

echo "[entrypoint] Running: ${CPP_EXE} ${SOLVE_ARGS[*]}"
set +e
"${CPP_EXE}" "${SOLVE_ARGS[@]}"
code=$?
set -e
echo "[entrypoint] Solver exit code: ${code}"
if [[ ${code} -ne 0 ]]; then
  echo "[entrypoint] ERROR: solver returned non-zero exit code ${code}" >&2
  exit "${code}"
fi

# Upload/Update shard to GCS
echo "[entrypoint] Uploading shard to ${OUT_GS}"
gsutil -q cp -n "${OUT_LOCAL}" "${OUT_GS}" || gsutil -q cp -a public-read "${OUT_LOCAL}" "${OUT_GS}"

# Optional local dedup for the shard (useful on resume), then re-upload
echo "[entrypoint] Running local dedup for shard..."
"${CPP_EXE}" --dedup "${OUT_LOCAL}" || true
echo "[entrypoint] Re-uploading deduped shard to ${OUT_GS}"
gsutil -q cp "${OUT_LOCAL}" "${OUT_GS}"

echo "[entrypoint] DONE. Object: ${OUT_GS}"