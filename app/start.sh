#!/bin/bash
# DKIM Watcher entrypoint — hardened
# Starts cron, cloudflared tunnel, and uvicorn

set -eo pipefail

# Trap SIGTERM/SIGINT for clean shutdown
cleanup() {
    echo "Shutting down..."
    kill %1 2>/dev/null  # kill cron
    kill %2 2>/dev/null  # kill cloudflared
    wait 2>/dev/null
    exit 0
}
trap cleanup SIGTERM SIGINT

# Create writable PID directory for cron
mkdir -p /tmp/cron
chown appuser:appuser /tmp/cron 2>/dev/null || true

# Start cron in background (ignore PID file errors)
cron -P /tmp/cron/crond.pid 2>/dev/null || cron 2>/dev/null || true
echo "Cron started"

# Start cloudflared tunnel in background
if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
    cloudflared tunnel --no-autoupdate run --token "${CLOUDFLARE_TUNNEL_TOKEN}" &
    echo "Cloudflared tunnel started"
else
    echo "WARNING: CLOUDFLARE_TUNNEL_TOKEN not set"
fi

# Run uvicorn in foreground (keeps container alive)
exec uvicorn main:app --host 127.0.0.1 --port 8001
