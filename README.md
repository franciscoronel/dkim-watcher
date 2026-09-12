# DKIM Watcher

A lightweight FastAPI service that monitors DKIM TXT records for a list of domains, stores results in SQLite, and serves a REST API plus static UI.

## Features

- **Automatic daily checks** — background job runs at 02:00 UTC via cron
- **Change detection** — tracks when each record last changed and how long unchanged
- **Key length detection** — parses DKIM public keys via cryptography to detect RSA key size changes (e.g. 2048-bit to 4096-bit rotations)
- **REST API** — list/export records, trigger manual checks, add/update/delete selectors (single or CSV import)
- **Static UI** — sortable columns, record count in header, export CSV, manual check button
- **SQLite persistence** — database mounted as volume
- **Docker hardened** — read-only rootfs, no-root user, cap-drop ALL

## Prerequisites

- Docker (with Docker Compose optional)
- [Cloudflare Tunnel token](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/configure-tunnels/local-management/tokens/) (required for the default hardened container setup)
  - If you don't have a custom domain, see [Running without Cloudflare](#running-without-cloudflare) below
- `curl` installed (for manual checks and cron jobs)

## Quick Start

### 1. Clone the repo

```bash
git clone <repo-url>
cd dkim-watcher
```

### 2. Create the data directory

```bash
mkdir -p /opt/data/db
```

### 3. Build and run with Cloudflare Tunnel

Replace `YOUR_TUNNEL_TOKEN` with your actual Cloudflare Tunnel token:

```bash
docker build -t dkim-watcher .

docker run -d \
  --name hermes_dkim \
  --read-only \
  --cap-drop ALL \
  --pids-limit 50 \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=100m \
  --tmpfs /var/run:rw,noexec,nosuid,size=100m \
  --tmpfs /tmp/cron:rw,noexec,nosuid,size=10m \
  -p 8000:8001 \
  -v /opt/data/db:/opt/data/db \
  -e CLOUDFLARE_TUNNEL_TOKEN='YOUR_TUNNEL_TOKEN' \
  dkim-watcher
```

The tunnel exposes the UI. Access it via your Cloudflare Tunnel URL.

### 4. Run without Cloudflare Tunnel (localhost)

If you don't have a Cloudflare Tunnel, start the container without the tunnel and access directly:

```bash
docker build -t dkim-watcher .

docker run -d \
  --name hermes_dkim \
  --read-only \
  --cap-drop ALL \
  --pids-limit 50 \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=100m \
  --tmpfs /var/run:rw,noexec,nosuid,size=100m \
  --tmpfs /tmp/cron:rw,noexec,nosuid,size=10m \
  -p 8000:8001 \
  -v /opt/data/db:/opt/data/db \
  dkim-watcher
```

Then access the UI at `http://localhost:8000/` or from the same network at `http://<server-ip>:8000/`.

For remote access without Cloudflare, you can use:
- **SSH reverse tunnel**: `ssh -R 8000:localhost:8001 user@remote-server`
- **Tailscale**: Install Tailscale on the server and access at `http://<device-name>:8000`
- **Nginx reverse proxy**: Point your domain's A record to the server and add a reverse proxy config

## Usage

### Adding selectors

1. Go to **Add New Selector** in the UI
2. Enter a domain and selector (single) or upload a CSV file (format: `domain,selector`)
3. CSV files must have a header row; duplicates are skipped with a warning

### Running a manual check

Click **Run DKIM Check** in the UI. The check is rate-limited to once per hour per run.

### Exporting data

Click **Export CSV** to download all records as a CSV file.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/dkim` | List all monitored DKIM records |
| `GET` | `/dkim/export/csv` | Export all records as CSV |
| `POST` | `/dkim/check` | Trigger an immediate check |
| `GET` | `/selectors/new` | Form to add a new selector |
| `POST` | `/selectors/new` | Add a selector (single or CSV upload) |
| `PUT` | `/selectors/{domain}/{selector}` | Update a selector |
| `DELETE` | `/selectors/{domain}/{selector}` | Delete a selector |

## Running the API Locally (Development)

For local development without Docker:

```bash
cd app
pip install -r ../requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

The UI is served from `app/static/` and the API at `http://localhost:8001/`.

## Cron Jobs

The container includes:
- **DKIM check** — runs daily at 02:00 UTC via `/dkim/check`
- **Daily backup** — backs up the SQLite DB, retains 30 days
- **Weekly backup** — backs up the SQLite DB, retains 90 days
- **Monthly backup** — backs up the SQLite DB, retains 365 days

Backups are stored in `/opt/data/db/backups/`.

## Architecture

```
Container
├── app/          — FastAPI application
│   ├── main.py   — FastAPI routes and startup
│   ├── models.py — SQLAlchemy models + DB init
│   ├── dkim.py   — DKIM record fetching and key length parsing
│   ├── start.sh  — Entrypoint: cron + cloudflared + uvicorn
│   └── static/   — HTML/CSS/JS frontend
├── cron/         — Shell scripts and cron definitions
├── uvicorn       — ASGI server (port 8001)
├── cron (system) — Daily DKIM check + backups
└── cloudflared   — Optional tunnel (if CLOUDFLARE_TUNNEL_TOKEN set)
```

## License

Private / Internal use
