#!/bin/bash
# DKIM Watcher entrypoint — hardened
# Starts the cloudflared tunnel and uvicorn.
# (No cron here: periodic DKIM checks run via APScheduler inside the app, and
# database backups are expected to run from a host-side cron on the host.)

set -eo pipefail

# Trap SIGTERM/SIGINT for clean shutdown
cleanup() {
    echo "Shutting down..."
    kill %1 2>/dev/null  # kill cloudflared
    wait 2>/dev/null
    exit 0
}
trap cleanup SIGTERM SIGINT

# Start cloudflared tunnel in background
if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
    cloudflared tunnel --no-autoupdate run --token "${CLOUDFLARE_TUNNEL_TOKEN}" &
    echo "Cloudflared tunnel started"
else
    echo "WARNING: CLOUDFLARE_TUNNEL_TOKEN not set"
fi

# Run uvicorn in foreground (keeps container alive).
# BIND_HOST defaults to 127.0.0.1: with a Cloudflare Tunnel the tunnel runs in
# this container and reaches the app over loopback, so nothing else can connect.
# Set BIND_HOST=0.0.0.0 only if you publish a port (-p) or want other machines
# on the network to reach the container directly.
exec uvicorn main:app --host "${BIND_HOST:-127.0.0.1}" --port 8001
