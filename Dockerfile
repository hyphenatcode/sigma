# Sigma backend.
#
# The native dependencies are the reason this image exists. WeasyPrint (§3.8)
# is a Python package that dlopens pango, cairo and harfbuzz at render time —
# it imports fine without them and then fails when someone asks for a PDF. A
# container pins that stack once instead of relitigating it on every host.
#
# Fonts matter for the same reason. The report template asks for
# "Times New Roman", which does not exist on Linux; fonts-liberation provides
# the metric-compatible substitute fontconfig maps it to, and fonts-dejavu-core
# covers the Turkish diacritics (ğ ü ş ı ö ç) if anything falls through. A slim
# image ships with no fonts at all, so without these the PDF renders boxes.

# ---------------------------------------------------------------------------
# Build stage — resolve Python dependencies into a self-contained virtualenv.
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Present so a dependency without a manylinux wheel can still build. None
# currently need it, and because this stage is discarded it costs build time
# rather than image size.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Runtime stage
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

# Package names verified against the libraries WeasyPrint actually loads:
#   libpango-1.0.so.0    -> libpango-1.0-0
#   libpangoft2-1.0.so.0 -> libpangoft2-1.0-0
#   libharfbuzz.so.0     -> libharfbuzz0b
#   libfontconfig.so.1   -> libfontconfig1
#   libcairo.so.2        -> libcairo2
# glib (libgobject-2.0) arrives as a pango dependency, so it is not listed
# explicitly — its package name differs between Debian and Ubuntu (the t64
# transition) and naming it would tie this file to one of them.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libfontconfig1 \
        libcairo2 \
        fonts-liberation \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY backend/ /app/backend/
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Uploaded datasets are written here only when STORAGE_DIR is left at its
# default. In a real deployment point storage at object storage (§7 specifies
# Cloudflare R2) — a container filesystem does not survive a redeploy.
RUN mkdir -p /app/backend/storage

RUN useradd --create-home --uid 10001 sigma && chown -R sigma:sigma /app
USER sigma

WORKDIR /app/backend
EXPOSE 8000

# Uses the venv's Python rather than curl, which is not installed.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

ENTRYPOINT ["/app/entrypoint.sh"]
