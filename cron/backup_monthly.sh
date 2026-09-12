#!/bin/bash
# Monthly DKIM database backup (gzipped with date)
set -euo pipefail

DB_PATH="/opt/data/db/dkim.db"
BACKUP_DIR="/opt/data/db/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/monthly_dkim_${TIMESTAMP}.db.gz"
RETENTION_MONTHS=12

# Create backup directory if it doesn't exist
mkdir -p "${BACKUP_DIR}"
chown -R appuser:appuser "${BACKUP_DIR}" 2>/dev/null || true

# Create compressed backup
if [ -f "${DB_PATH}" ]; then
    gzip -c "${DB_PATH}" > "${BACKUP_FILE}"
    chmod 644 "${BACKUP_FILE}"
    chown appuser:appuser "${BACKUP_FILE}" 2>/dev/null || true
    
    # Remove backups older than retention period (12 months)
    find "${BACKUP_DIR}" -name "monthly_dkim_*.db.gz" -type f -mtime +$((RETENTION_MONTHS * 30)) -delete 2>/dev/null || true
    
    echo "$(date): Monthly backup created: ${BACKUP_FILE}" >> /tmp/cron/backup.log
else
    echo "$(date): ERROR - Database not found at ${DB_PATH}" >> /tmp/cron/backup.log
fi
