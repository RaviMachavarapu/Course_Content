# syntax=docker/dockerfile:1
# typeset: Markdown + LaTeX formulas -> PDF via Quarto + xelatex.
# Multi-arch (linux/amd64 and linux/arm64): Quarto and TinyTeX both publish
# builds for each, so Apple Silicon builds natively (no emulation).
FROM python:3.12.7-slim-bookworm

ARG TARGETARCH
ARG QUARTO_VERSION=1.6.40
ARG TINYTEX_VERSION=v2026.10

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTEST_ADDOPTS="-p no:cacheprovider" \
    PATH=/opt/TinyTeX/bin/current:$PATH

# perl: tlmgr; xz-utils: TinyTeX archive; fonts-dejavu-core: Unicode text
# coverage (µ → ≤ ≥ × ° Greek); poppler-utils: pdftotext for the tests.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl perl xz-utils fontconfig fonts-dejavu-core poppler-utils \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/quarto.deb \
        "https://github.com/quarto-dev/quarto-cli/releases/download/v${QUARTO_VERSION}/quarto-${QUARTO_VERSION}-linux-${TARGETARCH}.deb" \
    && dpkg -i /tmp/quarto.deb && rm /tmp/quarto.deb \
    && quarto --version

# TinyTeX (pinned release), installed system-wide under /opt/TinyTeX.
# Extra packages (and the tlmgr self-update the arm64 repo insists on) come
# from the live TeX Live 2026 repository: not byte-pinned; when TeX Live 2027
# ships, bump TINYTEX_VERSION to a 2027 release.
RUN case "$TARGETARCH" in amd64) TT=x86_64;; arm64) TT=arm64;; *) echo "unsupported $TARGETARCH"; exit 1;; esac \
    && curl -fsSL "https://github.com/rstudio/tinytex-releases/releases/download/${TINYTEX_VERSION}/TinyTeX-linux-${TT}-${TINYTEX_VERSION}.tar.xz" \
        | tar -xJ -C /opt \
    && if [ -d /opt/.TinyTeX ]; then mv /opt/.TinyTeX /opt/TinyTeX; fi \
    && ln -s "$(ls -d /opt/TinyTeX/bin/*-linux)" /opt/TinyTeX/bin/current \
    && tlmgr option sys_bin /usr/local/bin \
    && tlmgr update --self \
    && tlmgr install mhchem chemgreek siunitx physics braket chemfig simplekv \
        cancel mathtools xstring fontspec unicode-math lm-math koma-script \
        bookmark xcolor geometry fancyvrb framed booktabs caption float \
        tcolorbox pgf environ trimspaces etoolbox amsmath amsfonts newunicodechar \
    && tlmgr path add \
    && fc-cache -f

WORKDIR /app
COPY header.tex unicode.tex warmup.md /app/
# Warm-up render: lets Quarto install anything its template still needs at
# build time (never at request time) and fills the font caches.
RUN mkdir -p /tmp/warm && cp /app/header.tex /app/unicode.tex /tmp/warm/ \
    && printf -- '---\ntitle: "Warm-up"\nformat:\n  pdf:\n    pdf-engine: xelatex\n    include-in-header: [header.tex, unicode.tex]\n    mainfont: DejaVu Serif\n    sansfont: DejaVu Sans\n    monofont: DejaVu Sans Mono\n---\n\n' > /tmp/warm/warm.qmd \
    && cat /app/warmup.md >> /tmp/warm/warm.qmd \
    && cd /tmp/warm && quarto render warm.qmd --to pdf \
    && test -s /tmp/warm/warm.pdf && rm -rf /tmp/warm

RUN pip install pytest==8.3.3

COPY server.py /app/server.py
COPY tests /app/tests

# Formulas are LaTeX from content generation: run unprivileged.
RUN useradd --create-home --uid 10001 typeset
USER typeset

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status == 200 else 1)"
CMD ["python3", "/app/server.py"]
