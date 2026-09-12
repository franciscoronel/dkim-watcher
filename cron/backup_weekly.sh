#!/bin/bash
# Weekly DKIM database backup (gzip compressed)
set -euo pipefail

DB_PATH="/opt/data/db/dkim.db"
BACKUP_DIR="/opt/data/db/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/weekly_dkim_${TIMESTAMP}.db.gz"
RETENTION_WEEKS=12

# Create backup directory if it doesn't exist
mkdir -p "${BACKUP_DIR}"
chown -R appuser:appuser "${BACKUP_DIR}" 2>/dev/null || true

# Create compressed backup
if [ -f "${DB_PATH}" ]; then
    gzip -c "${DB_PATH}" > "${BACKUP_FILE}"
    chmod 644 "${BACKUP_FILE}"
    chown appuser:appuser "${BACKUP_FILE}" 2>/dev/null || true
    
    # Remove backups older than retention period (12 weeks)
    find "${BACKUP_DIR}" -name "weekly_dkim_*.db.gz" -type f -mtime +$((RETENTION_WEEKS * 7)) -delete 2>/dev/null || true
    
    echo "$(date): Weekly backup created: ${BACKUP_FILE}" >> /tmp/cron/backup.log
else
    echo "$(date): ERROR - Database not found at ${DB_PATH}" >> /tmp/cron/backup.log
fi
