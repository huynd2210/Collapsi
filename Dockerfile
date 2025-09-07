# syntax=docker/dockerfile:1

# --- Builder stage: compile native solver ---
FROM debian:bookworm-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake ninja-build && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . /src
# Configure and build the solver
RUN cmake -G Ninja -S Collapsi/cpp -B /src/cpp-build -DCMAKE_BUILD_TYPE=Release \
 && cmake --build /src/cpp-build --parallel

# --- Runtime stage: python app + compiled solver ---
FROM python:3.11-slim AS runtime
# Ensure C++ runtime libs present for the solver binary
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# Copy application sources
COPY Collapsi /app/Collapsi

# Copy the compiled solver binary from the builder
COPY --from=builder /src/cpp-build/collapsi_cpp /app/Collapsi/collapsi_cpp
RUN chmod +x /app/Collapsi/collapsi_cpp

# Install Python dependencies
RUN pip install --no-cache-dir -r /app/Collapsi/requirements.txt

# Environment for strict solver usage in container
ENV COLLAPSI_CPP_EXE=/app/Collapsi/collapsi_cpp \
    COLLAPSI_REQUIRE_CPP=true \
    COLLAPSI_DEBUG=1 \
    COLLAPSI_DB=/tmp/collapsi.db

# Run from app dir where app.py lives
WORKDIR /app/Collapsi
EXPOSE 5000

# Use sh -c so $PORT expands at runtime on Render
CMD ["sh", "-c", "gunicorn -b 0.0.0.0:${PORT:-5000} app:app"]