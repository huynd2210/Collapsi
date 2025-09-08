# Collapsi on Google Cloud – batch solver with Cloud Run Jobs

This folder provides a production-ready path to generate the perfect-play database in Google Cloud using parallel shards, resumable runs, and GCS storage.

Components
- [gcp/Dockerfile](Collapsi/gcp/Dockerfile)
  - Multi-stage build that compiles the native C++ tools (collapsi_cpp, solve_norm_db) and packages them in a Cloud SDK runtime for gsutil + gcloud availability.
- [gcp/entrypoint.sh](Collapsi/gcp/entrypoint.sh)
  - Entry script for a single shard run. Resumes from an existing object if present and uploads the updated shard when done. Supports Cloud Run task arrays (taskCount / taskIndex).
- [gcp/merge_and_dedup.sh](Collapsi/gcp/merge_and_dedup.sh)
  - Convenience script to merge all shards under a prefix and deduplicate into one final DB artifact.
- Optional: a templated Cloud Run Job spec if you prefer declarative deployment (see the CLI below for a direct approach).

Prerequisites
- gcloud CLI authenticated and configured (roles to use Cloud Build, Artifact Registry, Cloud Run, and Storage)
- Project variables (substitute in all commands below):
  - PROJECT_ID=your-gcp-project
  - REGION=us-central1                # or your preferred region
  - REPO=collapsi                     # Artifact Registry repo name
  - BUCKET=your-gcs-bucket            # GCS bucket name (no gs://)
  - PREFIX=collapsi/solved_norm       # GCS object prefix (acts like a folder)

Enable required services
- gcloud services enable artifactregistry.googleapis.com run.googleapis.com cloudbuild.googleapis.com storage.googleapis.com

Create Artifact Registry repo
- gcloud artifacts repositories create $REPO --repository-format=docker --location=$REGION --description="Collapsi images"

Build and push image
- gcloud builds submit --region=$REGION --tag $REGION-docker.pkg.dev/$PROJECT_ID/$REPO/collapsi-solver:latest -f Collapsi/gcp/Dockerfile .

Prepare GCS bucket for output
- gsutil mb -l $REGION gs://$BUCKET

Grant Cloud Run Job runtime SA write access to the bucket (replace SA email if customized)
- SA_EMAIL=$(gcloud iam service-accounts list --format="value(email)" --filter="Compute Engine default service account" --project $PROJECT_ID)
- gsutil iam ch serviceAccount:$SA_EMAIL:objectAdmin gs://$BUCKET

Create the Cloud Run Job (sharded)
- Choose shard count (tasks) per run. Example with 8 parallel shards:
  - TASKS=8
  - gcloud run jobs create collapsi-solver \
      --image $REGION-docker.pkg.dev/$PROJECT_ID/$REPO/collapsi-solver:latest \
      --region $REGION \
      --tasks $TASKS \
      --max-retries 0 \
      --task-timeout 86400s \
      --cpu 4 --memory 8Gi \
      --set-env-vars BUCKET=$BUCKET,PREFIX=$PREFIX,LIMIT=10000000,BATCH=1000000

Run the job (starts all shards in parallel)
- gcloud run jobs execute collapsi-solver --region $REGION --wait

Resume a run
- Re-executing the job resumes each shard from its existing object (if present) thanks to [gcp/entrypoint.sh](Collapsi/gcp/entrypoint.sh). To extend solving or fill missed shards, just re-run execute.

Optional: preload "seen" from other DBs
- Provide a comma-separated list of gs:// URIs (e.g., previous runs or upstream datasets)
  - gcloud run jobs update collapsi-solver \
      --region $REGION \
      --set-env-vars SEEN_URIS="gs://$BUCKET/$PREFIX/seed.db,gs://another-bucket/path/known.db"

Merge shards and deduplicate
- Use the same image but override the command to run the merge script:
  - gcloud run jobs create collapsi-merge \
      --image $REGION-docker.pkg.dev/$PROJECT_ID/$REPO/collapsi-solver:latest \
      --region $REGION \
      --tasks 1 --max-retries 0 --cpu 2 --memory 4Gi \
      --set-env-vars BUCKET=$BUCKET,PREFIX=$PREFIX \
      --command "/opt/collapsi/merge_and_dedup.sh"
  - gcloud run jobs execute collapsi-merge --region $REGION --wait
  - The merged artifact will be uploaded to gs://$BUCKET/$PREFIX/solved_norm.merged.db

Controlling parallelism and shard mapping
- STRIDE (shard count) is auto-derived from Cloud Run’s taskCount via [gcp/entrypoint.sh](Collapsi/gcp/entrypoint.sh).
- OFFSET (shard index) is auto-derived from CLOUD_RUN_TASK_INDEX or BATCH_TASK_INDEX.
- You can override via env: STRIDE=..., OFFSET=...

Tuning
- CPU/memory: Increase --cpu/--memory for faster solving (and cost).
- LIMIT/BATCH: LIMIT is total records per shard target; BATCH controls flush frequency. Large batches reduce I/O but increase memory use.
- DUMP_DIR: set to enable tree dumps (diagnostics); otherwise leave blank.

Security
- The job needs Storage objectAdmin on the target bucket. Consider a dedicated service account with least-privilege and only this role on the bucket.

Cost Controls
- Reduce --tasks or --cpu/--memory to limit concurrent usage.
- Pause/stop by not executing the job; resume later (shards will pick up progress).