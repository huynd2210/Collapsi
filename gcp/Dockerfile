# syntax=docker/dockerfile:1

FROM debian:bookworm-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build git ca-certificates && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY cpp /app/cpp
WORKDIR /app/cpp
RUN cmake -S . -B build-ninja -G Ninja -DCMAKE_BUILD_TYPE=Release
RUN cmake --build build-ninja --target collapsi_cpp solve_norm_db -j $(nproc)

FROM gcr.io/google.com/cloudsdktool/google-cloud-cli:slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/collapsi
COPY --from=builder /app/cpp/build-ninja/collapsi_cpp /opt/collapsi/collapsi_cpp
COPY --from=builder /app/cpp/build-ninja/solve_norm_db /opt/collapsi/solve_norm_db
COPY gcp/entrypoint.sh /opt/collapsi/entrypoint.sh
COPY gcp/merge_and_dedup.sh /opt/collapsi/merge_and_dedup.sh
RUN chmod +x /opt/collapsi/entrypoint.sh /opt/collapsi/merge_and_dedup.sh
ENV PATH="/opt/collapsi:${PATH}"
ENTRYPOINT ["/opt/collapsi/entrypoint.sh"]