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

# Copy application sources (entire repo) to support both repo layouts:
# - app.py at repo root
# - or Collapsi/app.py under a subdir
COPY . /app

# Copy the compiled solver binary from the builder to a fixed path
COPY --from=builder /src/cpp-build/collapsi_cpp /app/collapsi_cpp
RUN chmod +x /app/collapsi_cpp

# Install Python dependencies (support both requirements.txt locations)
RUN if [ -f /app/requirements.txt ]; then pip install --no-cache-dir -r /app/requirements.txt; \
    elif [ -f /app/Collapsi/requirements.txt ]; then pip install --no-cache-dir -r /app/Collapsi/requirements.txt; \
    else echo "warning: requirements.txt not found"; fi

# Environment for strict solver usage in container
ENV COLLAPSI_CPP_EXE=/app/collapsi_cpp \
    COLLAPSI_REQUIRE_CPP=true \
    COLLAPSI_DEBUG=1 \
    COLLAPSI_DB=/tmp/collapsi.db

# Work from /app and dynamically choose where app.py lives at run time
WORKDIR /app
EXPOSE 5000

# If app.py exists at /app, run from there; otherwise try /app/Collapsi
CMD ["sh", "-c", "[ -f /app/app.py ] && cd /app || cd /app/Collapsi; exec gunicorn -b 0.0.0.0:${PORT:-5000} app:app"]