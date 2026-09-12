# Dockerfile for the DKIM monitor prototype
FROM python:3.13-slim

# Install system packages needed for cron, SQLite, and Cloudflare Tunnel
RUN apt-get update && \
    apt-get install -y --no-install-recommends cron sqlite3 ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# Install cloudflared
RUN curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && \
    chmod +x /usr/local/bin/cloudflared

# Create app directory and non-root user
WORKDIR /app

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# Set ownership of app directory
RUN chown -R appuser:appuser /app

# Install Python dependencies
COPY app/ /app
COPY app/static/ /app/static/
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Create data directory and set permissions
RUN mkdir -p /opt/data/db && chown -R appuser:appuser /opt/data

# Copy cron job definitions
COPY cron/dkim_check.sh /usr/local/bin/dkim_check.sh
RUN chmod +x /usr/local/bin/dkim_check.sh
COPY cron/monitor.cron /etc/cron.d/monitor
COPY cron/backup_daily.sh /usr/local/bin/backup_daily.sh
COPY cron/backup_weekly.sh /usr/local/bin/backup_weekly.sh
COPY cron/backup_monthly.sh /usr/local/bin/backup_monthly.sh
RUN chmod +x /usr/local/bin/backup_daily.sh /usr/local/bin/backup_weekly.sh /usr/local/bin/backup_monthly.sh
RUN crontab /etc/cron.d/monitor

# Start script
COPY app/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Switch to non-root user
USER appuser

# Expose FastAPI port
EXPOSE 8001

CMD ["/app/start.sh"]
