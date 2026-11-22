# Deploy image — used by the develop/prod GitHub workflows. Local development
# uses the base image directly (see compose.yaml).
ARG BASE_IMAGE=lapig/pasto-legal:base
FROM ${BASE_IMAGE}

WORKDIR /app

COPY . .

# Reconcile dependencies with this checkout's uv.lock if the base image is
# stale. With a matching lock this is a fast no-op.
RUN uv sync --frozen --no-cache
