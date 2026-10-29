# syntax=docker/dockerfile:1
FROM python:3.12.16-slim-trixie AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# System libraries:
#  - libpango / libcairo / libgdk-pixbuf / fonts  -> text and image rendering
#    (were WeasyPrint's; report PDFs are now typeset by the `typeset` service)
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
# constraints.txt pins every resolved version (see its header to regenerate).
RUN pip install --upgrade pip && pip install -c constraints.txt -e ".[dev]"

# Run as an unprivileged user with a fixed uid/gid (10001), which the compose
# `media-init` service hands the shared media volume to. /data/media is created
# here owned by it, so a brand-new named volume starts out writable.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /home/app --create-home \
        --shell /usr/sbin/nologin app \
    && mkdir -p /data/media \
    && chown app:app /data/media
USER app

EXPOSE 8000
# No --reload here: docker-compose.yml adds it for dev. Behind a proxy, also
# pass --forwarded-allow-ips=<proxy address> (see the api service).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
