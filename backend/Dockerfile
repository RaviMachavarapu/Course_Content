# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# System libraries:
#  - libpango / libcairo / libgdk-pixbuf / fonts  -> WeasyPrint (report PDF, T020)
#  - build-essential / libpq-dev                   -> psycopg build fallback
#  - libreoffice-impress + poppler-utils          -> slides: pptx -> pdf -> png (T018)
#  - graphviz                                     -> infographic: dot -> svg/png (T019, D15)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        fonts-dejavu-core \
        curl \
        libreoffice-impress \
        poppler-utils \
        graphviz \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .
RUN pip install --upgrade pip && pip install -e ".[dev]"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
