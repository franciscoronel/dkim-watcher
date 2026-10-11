# Dockerfile for the DKIM monitor prototype
# Base pinned to a specific patched build (2026-10-09) — closes the OpenSSL and
# gzip CVEs present in the previous 3.13.15-slim build.
FROM python:3.13.16-slim

# System packages actually used: ca-certificates + curl (healthcheck and the
# cloudflared download). cron was removed: the in-container cron layer never
# ran (it targeted port 8000 while uvicorn listens on 8001); periodic checks
# are handled by APScheduler in main.py and DB backups by the host-side cron.
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# cloudflared pinned to a specific release and verified against its published SHA256.
ARG CLOUDFLARED_VERSION=2026.10.0
ARG CLOUDFLARED_SHA256=d33ff2d14475178d2012c2c56beba87389ac5ded27649519f198a7d3134a99db
RUN curl -fsSL "https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-amd64" -o /usr/local/bin/cloudflared && \
    echo "${CLOUDFLARED_SHA256}  /usr/local/bin/cloudflared" | sha256sum -c - && \
    chmod +x /usr/local/bin/cloudflared

# Create app directory and non-root user
WORKDIR /app

# Create non-root user pinned to uid/gid 997/996 — the owner of the bind-mounted
# db directory on the testbed (a previous image used these ids; a mismatch makes
# SQLite writes fail with 500s on POST).
RUN groupadd -r -g 996 appuser && useradd -r -u 997 -g appuser -d /app -s /sbin/nologin appuser

# Set ownership of app directory
RUN chown -R appuser:appuser /app

# Install Python dependencies
COPY app/ /app
COPY app/static/ /app/static/
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Create data directory and set permissions
RUN mkdir -p /opt/data/db && chown -R appuser:appuser /opt/data

# Start script
COPY app/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Switch to non-root user
USER appuser

# Expose FastAPI port
EXPOSE 8001

CMD ["/app/start.sh"]
