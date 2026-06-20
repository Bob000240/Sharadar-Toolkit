# Multi-stage build for the QuorumNexus platform services.
# A single shared image runs migrations, ingestion, compute, signal, and eval
# entrypoints (selected via the container command). Later phases add
# service-specific images on top of this base.

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY . .
RUN pip install --upgrade pip && pip install .

# Default command applies the schema; compose / k8s override per service.
CMD ["alembic", "upgrade", "head"]
