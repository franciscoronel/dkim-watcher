# DKIM Watcher

A lightweight FastAPI service that monitors DKIM TXT records for a list of domains, stores results in SQLite, and serves a REST API plus static UI.

## Features

- **Automatic daily checks** — APScheduler inside the app runs `compare_and_update` daily at 02:00 UTC
- **Change detection** — tracks when each record last changed and how long unchanged
- **Key length detection** — parses DKIM public keys via cryptography to detect RSA key size changes (e.g. 2048-bit to 4096-bit rotations)
- **REST API** — list/export records, trigger manual checks, add/update/delete selectors (single or CSV import)
- **Static UI** — sortable columns with visible sort indicators, record count in header, export CSV, manual check button
- **SQLite persistence** — database mounted as volume
- **Docker hardened** — pinned base image, no-root user (fixed uid/gid), read-only rootfs, cap-drop ALL, pinned + checksummed `cloudflared`

## Prerequisites

- Docker (with Docker Compose optional)
- [Cloudflare Tunnel token](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/configure-tunnels/local-management/tokens/) (required for the default hardened container setup)
  - If you don't have a custom domain, see [Running without Cloudflare](#running-without-cloudflare) below

## Quick Start

### 1. Clone the repo

```bash
git clone <repo-url>
cd dkim-watcher
```

### 2. Create the data directory

The container runs as a non-root user with uid **997** / gid **996** (pinned in the `Dockerfile`). The bind-mounted data directory must be owned by that uid, otherwise every write to SQLite fails with a 500 (`unable to open database file`):

```bash
mkdir -p /opt/data/db
sudo chown -R 997:996 /opt/data/db
chmod 755 /opt/data/db
```

No sudo? A root container can do the chown for you:

```bash
docker run --rm -v /opt/data/db:/mnt busybox chown -R 997:996 /mnt
```

Avoid `chmod 777` as the fix. It works, but it grants write access to every uid on the host, which is a wider surface than the app needs — ownership is the correct mechanism here. Use `777` only as a last resort on a host where you genuinely cannot change ownership, and set `666` on an existing `dkim.db` in that case.

### 3. Build and run with Cloudflare Tunnel

Replace `YOUR_TUNNEL_TOKEN` with your actual Cloudflare Tunnel token:

```bash
docker build -t dkim-watcher .

docker run -d \
  --name dkim-watcher \
  --restart unless-stopped \
  --read-only \
  --cap-drop ALL \
  --pids-limit 50 \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=100m \
  --tmpfs /var/run:rw,noexec,nosuid,size=100m \
  --health-cmd 'curl -f http://127.0.0.1:8001/' \
  --health-interval 30s \
  --health-timeout 10s \
  --health-retries 3 \
  --health-start-period 10s \
  -v /opt/data/db:/opt/data/db \
  -e CLOUDFLARE_TUNNEL_TOKEN='YOUR_TUNNEL_TOKEN' \
  dkim-watcher
```

The tunnel exposes the UI. Access it via your Cloudflare Tunnel URL. No port is published: with a tunnel the container is reachable only through Cloudflare, which is the safer default. Add `-p 127.0.0.1:8001:8001` if you also want local access.

### 4. Run without Cloudflare Tunnel (localhost)

If you don't have a Cloudflare Tunnel, start the container without the tunnel and access directly:

```bash
docker build -t dkim-watcher .

docker run -d \
  --name dkim-watcher \
  --restart unless-stopped \
  --read-only \
  --cap-drop ALL \
  --pids-limit 50 \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=100m \
  --tmpfs /var/run:rw,noexec,nosuid,size=100m \
  --health-cmd 'curl -f http://127.0.0.1:8001/' \
  --health-interval 30s \
  --health-timeout 10s \
  --health-retries 3 \
  --health-start-period 10s \
  -p 127.0.0.1:8001:8001 \
  -v /opt/data/db:/opt/data/db \
  -e BIND_HOST=0.0.0.0 \
  dkim-watcher
```

Then access the UI at `http://localhost:8001/` or from the same network at `http://<server-ip>:8001/` (drop the `127.0.0.1:` prefix to bind all interfaces).

`BIND_HOST=0.0.0.0` is required in this case. The app defaults to binding `127.0.0.1` **inside** the container, which is correct when the Cloudflare Tunnel runs alongside it — but a published port (`-p`) cannot reach a loopback-only listener, so without this variable the container will look healthy while every request to the published port fails.

For remote access without Cloudflare, you can use:
- **SSH reverse tunnel**: `ssh -R 8001:localhost:8001 user@remote-server`
- **Tailscale**: Install Tailscale on the server and access at `http://<device-name>:8001`
- **Nginx reverse proxy**: Point your domain's A record to the server and add a reverse proxy config

If you put the app behind an authenticating proxy, keep the app itself unauthenticated and let the proxy handle access (Cloudflare Access, Basic auth, mTLS). The app has no built-in login.

## Usage

### Adding selectors

1. Go to **Add New Selector** in the UI
2. Enter a domain and selector (single) or upload a CSV file (format: `domain,selector`)
3. A header row is allowed and skipped automatically; duplicates are skipped and reported. Invalid names are rejected — see [Validation](#validation).

Submitting the form returns you to the main list with the new row in place. If the add fails (duplicate or invalid input) you stay on the form and the reason is shown.

### Running a manual check

Click **Run DKIM Check** in the UI. The check is rate-limited to once per hour per run.

### Exporting data

Click **Export CSV** to download all records as a CSV file.

### Sorting the table

Column headers that can be sorted show a neutral `↕` marker and a pointer cursor; clicking sorts ascending, clicking again sorts descending, and the active column is highlighted with `▲`/`▼`. Sorting is client-side and is re-applied after the table refreshes.

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

`/docs`, `/redoc` and `/openapi.json` are disabled: they expose the whole API surface to anyone who reaches the origin.

## Validation

Domain and selector are validated on add and on rename, so malformed or hostile input never reaches the database or the page:

- **Domain** — 2–253 chars, dot-separated DNS labels of 1–63 chars using letters, digits, hyphens and underscores; no leading/trailing hyphen.
- **Selector** — up to 127 chars, dot-separated DNS labels (dots are allowed so `google._domainkey` works).
- A rename that would collide with an existing pair is rejected.
- CSV import is capped at 1 MB and 5,000 rows, and is decoded as UTF-8 with replacement so a non-UTF-8 file cannot crash the request. Rejected rows are returned in an `invalid` list.

## Scheduled Checks & Backups

The app schedules its own daily check with APScheduler (`main.py`, 02:00 UTC). There is no system cron in the image — an earlier build shipped one, but its jobs targeted port 8000 while uvicorn listens on 8001, so they never ran.

Backups are your responsibility. A host-side cron entry is the simplest option:

```cron
0 3 * * * cp /opt/data/db/dkim.db /var/backups/dkim/dkim_$(date +\%Y\%m\%d).db
```

Use `sqlite3 /opt/data/db/dkim.db ".backup /path/to/backup.db"` instead of `cp` if the app may be writing at backup time.

## Security Notes

- **Base image pinned** to a specific patched build (`python:3.13.16-slim`) rather than a floating `latest`, so a rebuild is reproducible and CVE fixes are applied deliberately.
- **Dependencies pinned** to exact versions in `requirements.txt`, verified clean against OSV with `pip-audit`.
- **`cloudflared` pinned** to a named release and verified against its published SHA256 instead of `releases/latest/download`.
- **Non-root, fixed uid/gid** (997/996), read-only rootfs, `cap-drop ALL`, `no-new-privileges`, pids limit.
- **CSP header** on every HTML response: `default-src 'self'`, `script-src 'self' 'unsafe-inline'` (the UI uses inline scripts), `style-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`.
- **No inline HTML built from data**: the UI writes cell text with `textContent`, so a stored value cannot inject markup.
- If you serve this over HTTPS, enable HSTS with a real `max-age` at your proxy or CDN — the app does not set it.

## Running the API Locally (Development)

For local development without Docker:

```bash
cd app
pip install -r ../requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

Run it from the `app/` directory, matching the container layout (`WORKDIR /app`, `uvicorn main:app`). `app/models.py` hardcodes `DB_PATH = "/opt/data/db/dkim.db"`; point it somewhere local if you don't want to touch the real database.

The UI is served from `app/static/` and the API at `http://localhost:8001/`.

## Architecture

```
Container
├── app/          — FastAPI application
│   ├── main.py   — FastAPI routes, CSP middleware, APScheduler job
│   ├── models.py — SQLAlchemy models + DB init
│   ├── dkim.py   — DKIM record fetching and key length parsing
│   ├── start.sh  — Entrypoint: cloudflared + uvicorn
│   └── static/   — HTML/CSS/JS frontend
├── uvicorn       — ASGI server (port 8001)
└── cloudflared   — Optional tunnel (if CLOUDFLARE_TUNNEL_TOKEN set)
```

## License

Private / Internal use
