# dkim.py

import dns.resolver
import time
from datetime import datetime
from models import SessionLocal, DKIMRecord, DKIMSelector
import re
import base64

def get_key_length(txt_record: str) -> int | None:
    if not txt_record:
        return None
    # Grab everything after p= (handles split TXT records with quotes/spaces)
    match = re.search(r'p=\s*(.+)', txt_record)
    if not match:
        return None
    # Strip everything except base64 characters
    key_b64 = re.sub(r'[^A-Za-z0-9+/=]', '', match.group(1))
    if not key_b64:
        return None
    # Add padding (Python 3.13 b64decode is strict by default)
    padding_needed = (4 - len(key_b64) % 4) % 4
    key_b64_padded = key_b64 + '=' * padding_needed
    try:
        from cryptography.hazmat.primitives import serialization
        der_data = base64.b64decode(key_b64_padded)
        public_key = serialization.load_der_public_key(der_data)
        return public_key.key_size
    except Exception:
        return None

def fetch_txt(domain: str, selector: str) -> str | None:
    name = f"{selector}._domainkey.{domain}"
    try:
        answers = dns.resolver.resolve(name, "TXT")
        return "".join([txt.to_text().strip('"') for txt in answers])
    except Exception:
        return None

def compare_and_update():
    db = SessionLocal()
    try:
        # Load monitored selectors on-demand during function execution
        monitored = [
            {"domain": s.domain, "selector": s.selector}
            for s in db.query(DKIMSelector).all()
        ]

        for item in monitored:
            domain, selector = item["domain"], item["selector"]
            new_txt = fetch_txt(domain, selector)

            # Calculate key length if we have a new TXT record
            key_length = get_key_length(new_txt) if new_txt else None

            rec = db.query(DKIMRecord).filter_by(domain=domain, selector=selector).first()
            if rec is None:
                rec = DKIMRecord(
                    domain=domain,
                    selector=selector,
                    txt=new_txt,
                    key_length=key_length,
                    last_checked=datetime.utcnow(),
                    changed_at=datetime.utcnow() if new_txt else None,
                    unchanged_for=0,
                    changed=bool(new_txt),
                )
                db.add(rec)
            else:
                rec.last_checked = datetime.utcnow()
                if new_txt != rec.txt:
                    rec.changed = True
                    rec.changed_at = datetime.utcnow()
                    rec.unchanged_for = 0
                    rec.txt = new_txt
                    rec.key_length = key_length
                else:
                    rec.changed = False
                    rec.unchanged_for = (
                        (rec.last_checked - rec.changed_at).days
                        if rec.changed_at
                        else 0
                    )
                    rec.key_length = key_length

            # Add a delay between lookups to prevent rate limiting/congestion
            time.sleep(1)

        db.commit()
    finally:
        db.close()
