from contextlib import asynccontextmanager
from datetime import datetime
import os
import re
from fastapi import FastAPI, Depends, Form, Request, UploadFile, File
from typing import Optional
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from apscheduler.schedulers.background import BackgroundScheduler

from models import init_db, SessionLocal, DKIMRecord, DKIMSelector
from dkim import compare_and_update

# Ensure DB is created BEFORE starting FastAPI and APScheduler
init_db()

# Docs/redoc/OpenAPI are disabled in production: they expose the whole API
# surface to anyone who reaches the origin.
app = FastAPI(title="DKIM Watcher", docs_url=None, redoc_url=None, openapi_url=None)

# Defense-in-depth CSP for HTML responses. Inline scripts are used by the UI,
# so script-src must allow 'unsafe-inline'; everything else is locked down.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)


@app.middleware("http")
async def csp_header(request: Request, call_next):
    response = await call_next(request)
    ctype = response.headers.get("content-type", "")
    if ctype.startswith("text/html"):
        response.headers["content-security-policy"] = _CSP
    return response


# Limits for CSV bulk import
MAX_CSV_BYTES = 1_000_000
MAX_CSV_ROWS = 5_000

# Scheduler: run every day at 02:00 UTC
scheduler = BackgroundScheduler()
scheduler.add_job(compare_and_update, "cron", hour=2, minute=0)
scheduler.start()

# Dependency: DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# API: list all records
@app.get("/dkim", response_model=list[dict])
def list_records(db: SessionLocal = Depends(get_db)):
    return [
        {
            "domain": r.domain,
            "selector": r.selector,
            "txt": r.txt,
            "key_length": r.key_length,
            "last_checked": r.last_checked,
            "changed_at": r.changed_at,
            "unchanged_for": r.unchanged_for,
            "changed": r.changed,
        }
        for r in db.query(DKIMRecord).all()
    ]

# New endpoint: export records as CSV
import csv
import io

@app.get("/dkim/export/csv")
def export_csv(db: SessionLocal = Depends(get_db)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["domain", "selector", "txt", "last_checked", "changed_at", "unchanged_for", "changed"])
    for r in db.query(DKIMRecord).all():
        writer.writerow([
            r.domain,
            r.selector,
            r.txt,
            r.last_checked.isoformat() if r.last_checked else "",
            r.changed_at.isoformat() if r.changed_at else "",
            r.unchanged_for,
            r.changed,
        ])
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=dkim_records.csv"})

# Rate limiter state for manual check
# Max 1 per hour, max 6 per day
_manual_checks = {"count": 0, "day": 0, "last_hour": 0}


def _check_rate_limit():
    now = datetime.utcnow()
    today = now.day

    # Reset daily counter if new day
    if _manual_checks["day"] != today:
        _manual_checks["count"] = 0
        _manual_checks["day"] = today

    # Reject if >6/day
    if _manual_checks["count"] >= 6:
        return False, "Rate limit exceeded: 6 checks per day maximum"

    # Reset hourly counter if >1 hour since last check
    if now.hour != _manual_checks["last_hour"]:
        _manual_checks["last_hour"] = now.hour
        _manual_checks["_hour_count"] = 0

    # Reject if already used 1 this hour
    if _manual_checks.get("_hour_count", 0) >= 1:
        return False, "Rate limit exceeded: 1 check per hour maximum"

    _manual_checks["count"] += 1
    _manual_checks["_hour_count"] = _manual_checks.get("_hour_count", 0) + 1
    return True, "OK"


# API: trigger a manual check (useful for dev)
@app.post("/dkim/check")
def manual_check(db: SessionLocal = Depends(get_db)):
    allowed, msg = _check_rate_limit()
    if not allowed:
        return {"status": "rate_limited", "message": msg}
    compare_and_update()
    return {"status": "checked", "time": datetime.utcnow()}

# Serve the static UI
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def read_index():
    response = FileResponse(os.path.join(STATIC_DIR, "index.html"))
    response.headers["cache-control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["pragma"] = "no-cache"
    response.headers["expires"] = "0"
    return response

@app.get("/selectors/new")
def new_selector_form():
    response = FileResponse(os.path.join(STATIC_DIR, "new_selector.html"))
    response.headers["cache-control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["pragma"] = "no-cache"
    response.headers["expires"] = "0"
    return response

def _valid_dns_label(value: str) -> bool:
    """A DNS label as used in practice for DKIM selectors: 1-63 chars of
    letters/digits/hyphen/underscore, no leading or trailing hyphen.
    Underscores are allowed because selectors like `google._domainkey` are common."""
    if not value or len(value) > 63:
        return False
    if not re.fullmatch(r"[a-z0-9_][-a-z0-9_]*", value):
        return False
    return not (value.startswith("-") or value.endswith("-"))


def _valid_domain(value: str) -> bool:
    """Dot-separated DNS labels, at least two labels, total length <= 253."""
    if not value or len(value) > 253:
        return False
    labels = value.split(".")
    if len(labels) < 2:
        return False
    return all(_valid_dns_label(l) for l in labels)


def _valid_selector(value: str) -> bool:
    """Selectors may contain dots (e.g. google._domainkey), each part a DNS label."""
    if not value or len(value) > 127:
        return False
    return all(_valid_dns_label(l) for l in value.split("."))


def _add_selector_pair(db, domain: str, selector: str, added: list, duplicates: list, invalid: list):
    """Insert a DKIMSelector + DKIMRecord pair if not already present."""
    domain = domain.strip().lower()
    selector = selector.strip().lower()
    if not domain or not selector:
        return
    if not _valid_domain(domain) or not _valid_selector(selector):
        invalid.append(f"{domain}::{selector}")
        return
    existing = db.query(DKIMSelector).filter_by(domain=domain, selector=selector).first()
    if existing:
        duplicates.append(f"{domain}::{selector}")
        return
    new_sel = DKIMSelector(domain=domain, selector=selector)
    db.add(new_sel)
    new_rec = DKIMRecord(domain=domain, selector=selector, txt='', last_checked=datetime.utcnow(), unchanged_for=0, changed=False)
    db.add(new_rec)
    added.append(f"{domain}::{selector}")

@app.post("/selectors/new")
async def add_selector(
    domain: Optional[str] = Form(None),
    selector: Optional[str] = Form(None),
    csv_file: Optional[UploadFile] = File(None),
    db: SessionLocal = Depends(get_db),
):
    # CSV upload path (only when a real file with a name is provided)
    if csv_file and csv_file.filename:
        content = await csv_file.read()
        if not content:
            return {"status": "error", "message": "CSV file is empty"}
        if len(content) > MAX_CSV_BYTES:
            return {"status": "error", "message": f"CSV file too large (max {MAX_CSV_BYTES} bytes)"}
        reader = csv.reader(content.decode("utf-8", errors="replace").splitlines())
        added = []
        duplicates = []
        invalid = []
        rows = list(reader)
        if len(rows) > MAX_CSV_ROWS:
            return {"status": "error", "message": f"Too many CSV rows (max {MAX_CSV_ROWS})"}
        # Skip a header row if present (domain,selector / selector,domain)
        if rows and rows[0] and rows[0][0].strip().lower() in ("domain", "selector"):
            rows = rows[1:]
        for row in rows:
            if len(row) == 1:
                # Single FQDN column: selector.domain.tld
                fqdn = row[0].strip()
                if "." not in fqdn:
                    continue
                parts = fqdn.split(".")
                sel = parts[0]
                dom = ".".join(parts[1:])
            elif len(row) == 2:
                # Two columns: domain,selector
                dom, sel = row[0].strip(), row[1].strip()
            else:
                continue
            _add_selector_pair(db, dom, sel, added, duplicates, invalid)
        db.commit()
        return {"status": "csv_imported", "added": added, "duplicates": duplicates, "invalid": invalid}

    # Single form path
    if not domain or not selector:
        return {"status": "error", "message": "Domain and Selector are required if no CSV is provided"}
    clean_domain = domain.strip().lower()
    clean_selector = selector.strip().lower()
    if not _valid_domain(clean_domain) or not _valid_selector(clean_selector):
        return {"status": "error", "message": "Invalid domain or selector (letters, digits, hyphens, underscores and dots only)"}
    added = []
    duplicates = []
    invalid = []
    _add_selector_pair(db, clean_domain, clean_selector, added, duplicates, invalid)
    db.commit()
    if invalid:
        return {"status": "error", "message": "Invalid domain or selector"}
    if duplicates:
        return {"status": "error", "message": f"Selector already exists: {duplicates[0]}"}
    return {"status": "added", "domain": clean_domain, "selector": clean_selector}

# List selectors
@app.get("/selectors")
def list_selectors(db: SessionLocal = Depends(get_db)):
    return [
        {"domain": s.domain, "selector": s.selector}
        for s in db.query(DKIMSelector).all()
    ]

# Delete selector
@app.delete("/selectors/{domain}/{selector}")
def delete_selector(domain: str, selector: str, db: SessionLocal = Depends(get_db)):
    sel = db.query(DKIMSelector).filter_by(domain=domain, selector=selector).first()
    if not sel:
        return {"status": "not_found"}
    db.delete(sel)
    # Also remove the matching record so the main page stays in sync
    rec = db.query(DKIMRecord).filter_by(domain=domain, selector=selector).first()
    if rec:
        db.delete(rec)
    db.commit()
    return {"status": "deleted"}

# Update selector
from pydantic import BaseModel

class SelectorUpdate(BaseModel):
    domain: Optional[str] = None
    selector: Optional[str] = None

@app.put("/selectors/{domain}/{selector}")
def update_selector(domain: str, selector: str, body: SelectorUpdate, db: SessionLocal = Depends(get_db)):
    sel = db.query(DKIMSelector).filter_by(domain=domain, selector=selector).first()
    if not sel:
        return {"status": "not_found"}
    new_domain = (body.domain or sel.domain).strip().lower()
    new_selector = (body.selector or sel.selector).strip().lower()
    if not _valid_domain(new_domain) or not _valid_selector(new_selector):
        return {"status": "error", "message": "Invalid domain or selector"}
    # Reject a rename that would collide with an existing pair
    collision = db.query(DKIMSelector).filter_by(domain=new_domain, selector=new_selector).first()
    if collision and (collision.domain, collision.selector) != (sel.domain, sel.selector):
        return {"status": "error", "message": f"Selector already exists: {new_domain}::{new_selector}"}
    sel.domain = new_domain
    sel.selector = new_selector
    # Keep the record table in sync
    rec = db.query(DKIMRecord).filter_by(domain=domain, selector=selector).first()
    if rec:
        rec.domain = new_domain
        rec.selector = new_selector
    db.commit()
    return {"status": "updated"}
