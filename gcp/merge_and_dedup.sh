#!/usr/bin/env bash
set -euo pipefail

# Merge all shard objects under a GCS prefix into a single local DB file and deduplicate.
#
# Required env:
#   BUCKET   GCS bucket name (no gs://)
#   PREFIX   Object prefix (directory) where shard files live
#
# Optional env:
#   OUT_NAME   Final merged filename (default: solved_norm.merged.db)
#   TMP_DIR    Local working directory (default: /opt/collapsi/work/merge)
#
# Result:
#   - Local merged, deduped file at ${TMP_DIR}/${OUT_NAME}
#   - Uploaded to gs://BUCKET/PREFIX/${OUT_NAME}

: "${BUCKET:?BUCKET required}"
: "${PREFIX:?PREFIX required}"
OUT_NAME="${OUT_NAME:-solved_norm.merged.db}"
TMP_DIR="${TMP_DIR:-/opt/collapsi/work/merge}"

mkdir -p "${TMP_DIR}"
OUT_LOCAL="${TMP_DIR}/${OUT_NAME}"
OUT_GS="gs://${BUCKET}/${PREFIX}/${OUT_NAME}"

echo "[merge] Listing shards under gs://${BUCKET}/${PREFIX}"
mapfile -t SHARDS < <(gsutil ls "gs://${BUCKET}/${PREFIX}/solved_norm.offset"*.db 2>/dev/null || true)
if [[ ${#SHARDS[@]} -eq 0 ]]; then
  echo "[merge] No shard files found. Nothing to merge."
  exit 0
fi

echo "[merge] Found ${#SHARDS[@]} shard(s). Downloading to ${TMP_DIR}/shards"
SHARD_DIR="${TMP_DIR}/shards"
mkdir -p "${SHARD_DIR}"
for uri in "${SHARDS[@]}"; do
  echo "[merge]   -> ${uri}"
  gsutil -q cp "${uri}" "${SHARD_DIR}/"
done

echo "[merge] Concatenating binary records into ${OUT_LOCAL}"
rm -f "${OUT_LOCAL}"
# Concatenate in lexical order to maintain determinism; dedup will handle duplicates anyway.
LC_ALL=C sort -V <(printf "%s\n" "${SHARDS[@]}") | while read -r uri; do
  base="$(basename "${uri}")"
  cat "${SHARD_DIR}/${base}" >> "${OUT_LOCAL}"
done

echo "[merge] Running deduplication using solve_norm_db --dedup"
# The solver tool in this image can deduplicate a single file in-place (writes .bak and atomically replaces)
if command -v /opt/collapsi/solve_norm_db >/dev/null 2>&1; then
  /opt/collapsi/solve_norm_db --dedup "${OUT_LOCAL}" || true
else
  echo "[merge] WARN: /opt/collapsi/solve_norm_db not found; skipping dedup."
fi

echo "[merge] Uploading merged DB to ${OUT_GS}"
gsutil -q cp "${OUT_LOCAL}" "${OUT_GS}"

echo "[merge] DONE"