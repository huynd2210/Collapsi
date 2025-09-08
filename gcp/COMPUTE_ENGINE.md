# Collapsi on Google Compute Engine (GCE)

This guide shows how to run the native solver on Compute Engine VMs using the same container image built in [gcp/Dockerfile](Collapsi/gcp/Dockerfile). This is ideal if you want full control over machine type, local SSDs, or prefer VMs over serverless.

Recommended approach: use “create-with-container” so GCE runs our container directly, including Artifact Registry auth, without extra setup.

Prerequisites
- You’ve built and pushed the image per [gcp/README.md](Collapsi/gcp/README.md):
  - Image: $REGION-docker.pkg.dev/$PROJECT_ID/$REPO/collapsi-solver:latest
- GCS bucket to write results (and resumable shards):
  - BUCKET=your-bucket-name (no gs:// prefix)
  - PREFIX=collapsi/solved_norm (folder-like prefix in your bucket)
- Grant the VM service account Storage objectAdmin on the bucket (least privilege for write).

Option A — Single powerful VM (no sharding)
- Simplest: one VM runs the entire job (may be long-running).
- Example (c2-standard-32, Spot/Preemptible to save cost):
  - gcloud compute instances create-with-container collapsi-single \
      --zone=$ZONE \
      --provisioning-model=SPOT --instance-termination-action=STOP \
      --machine-type=c2-standard-32 \
      --scopes=https://www.googleapis.com/auth/cloud-platform \
      --service-account=$SA_EMAIL \
      --container-image=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/collapsi-solver:latest \
      --container-env=BUCKET=$BUCKET,PREFIX=$PREFIX,STRIDE=1,OFFSET=0,LIMIT=10000000,BATCH=1000000

- The container writes/updates gs://$BUCKET/$PREFIX/solved_norm.offset0.stride1.db and resumes if you restart the VM.

Option B — Multiple VMs for sharded parallelism (recommended)
- Run N identical VMs, each with a unique OFFSET in [0..N-1] and STRIDE=N.
- Example with 8 shards on c2-standard-16:
  - TASKS=8
  - for i in $(seq 0 $((TASKS-1))); do
      gcloud compute instances create-with-container collapsi-shard-$i \
        --zone=$ZONE \
        --provisioning-model=SPOT --instance-termination-action=STOP \
        --machine-type=c2-standard-16 \
        --scopes=https://www.googleapis.com/auth/cloud-platform \
        --service-account=$SA_EMAIL \
        --container-image=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/collapsi-solver:latest \
        --container-env=BUCKET=$BUCKET,PREFIX=$PREFIX,STRIDE=$TASKS,OFFSET=$i,LIMIT=10000000,BATCH=1000000
    done

- Each VM updates its own shard:
  - gs://$BUCKET/$PREFIX/solved_norm.offset<i>.stride<TASKS>.db
- You can stop/start VMs (or recreate) to resume; shards are resumable by design.

Monitoring and logs
- View serial console logs:
  - gcloud compute instances get-serial-port-output collapsi-shard-0 --zone=$ZONE
- SSH to a VM and tail container logs (COS/Container-Optimized OS uses containerd; logs are streamed to serial console).

Merging shards
- After shards complete (or periodically), merge and dedup into a single DB:
  - You can use the Cloud Run merge job in [gcp/README.md](Collapsi/gcp/README.md), or run the same container on a small VM and call:
    - /opt/collapsi/merge_and_dedup.sh (see [gcp/merge_and_dedup.sh](Collapsi/gcp/merge_and_dedup.sh))
- Result: gs://$BUCKET/$PREFIX/solved_norm.merged.db

Resuming / extending runs
- Recreate any missing or preempted shards with the same STRIDE/OFFSET; they resume from their existing object.
- You may run additional passes to increase LIMIT for deeper coverage; each pass appends new records and dedups locally before uploading.

Instance groups (advanced)
- Managed Instance Groups (MIG) can scale shards automatically, but distributing a unique OFFSET to each instance requires per-instance metadata or a custom controller. For most use cases, creating a fixed number of single VMs with unique OFFSET values as shown above is simpler and robust.

Cost tips
- Use Spot/Preemptible VMs for cost savings; shards are resumable.
- c2-standard or c3-standard are strong choices; adjust CPU/memory based on your throughput/cost balance.
- Local SSDs can improve scratch I/O for very large batches; ensure you upload frequently to GCS.

Security
- Use a dedicated service account with only Storage objectAdmin on the target bucket.
- If using Artifact Registry in a private project, ensure the VM service account has Artifact Registry Reader on the image repo.

Environment reference
- The container reads:
  - BUCKET (required): GCS bucket name (no gs://)
  - PREFIX (default: collapsi/solved_norm)
  - STRIDE (default: 1)
  - OFFSET (default: 0)
  - LIMIT (default: 10000000)
  - BATCH (default: 1000000)
  - SEEN_URIS (optional): comma-separated gs:// URIs to preload “seen” records
  - DUMP_DIR (optional): path inside VM for optional solver tree dumps
- Produces per-shard object:
  - gs://$BUCKET/$PREFIX/solved_norm.offset$OFFSET.stride$STRIDE.db

Troubleshooting
- Permission denied pulling image:
  - Ensure VM service account has Artifact Registry Reader for $REPO, or use a public repo.
- Permission denied writing to bucket:
  - Ensure VM service account has Storage objectAdmin on gs://$BUCKET.
- Preempted VM:
  - Just recreate the VM with the same OFFSET and STRIDE to resume.