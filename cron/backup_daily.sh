#!/bin/bash
# Daily DKIM database backup
set -euo pipefail

DB_PATH="/opt/data/db/dkim.db"
BACKUP_DIR="/opt/data/db/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/daily_dkim_${TIMESTAMP}.db"
RETENTION_DAYS=30

# Create backup directory if it doesn't exist
mkdir -p "${BACKUP_DIR}"
chown -R appuser:appuser "${BACKUP_DIR}" 2>/dev/null || true

# Copy database (safe since we're on read-only rootfs but db is mounted volume)
if [ -f "${DB_PATH}" ]; then
    cp "${DB_PATH}" "${BACKUP_FILE}"
    chmod 644 "${BACKUP_FILE}"
    chown appuser:appuser "${BACKUP_FILE}" 2>/dev/null || true
    
    # Remove backups older than retention period
    find "${BACKUP_DIR}" -name "daily_dkim_*.db" -type f -mtime +${RETENTION_DAYS} -delete 2>/dev/null || true
    
    echo "$(date): Daily backup created: ${BACKUP_FILE}" >> /tmp/cron/backup.log
else
    echo "$(date): ERROR - Database not found at ${DB_PATH}" >> /tmp/cron/backup.log
fi
