#!/bin/bash
# Nightly backup for the A7 WhatsApp inbox.
#
# Chats are kept forever by design, so losing the database loses history nobody
# can reconstruct — the gateway's own retention is not a fallback. The dump is
# small (text), so it runs daily; attachments are bulky and change slowly, so
# they are archived weekly.
#
# Both copies live on the same disk as the data they protect, which guards
# against a bad migration or an accidental delete, not against losing the
# machine. The VPS provider's own snapshots cover that case.
#
# Installed at /opt/a7-wa/deploy/backup.sh and run from cron.

set -euo pipefail

ROOT=/opt/a7-wa
BACKUPS="$ROOT/backups"
COMPOSE_DIR="$ROOT/deploy"
KEEP_DB_DAYS=14
KEEP_MEDIA_WEEKS=8

mkdir -p "$BACKUPS"
cd "$COMPOSE_DIR"

# shellcheck disable=SC1091
set -a; . ./.env; set +a

STAMP=$(date +%Y%m%d-%H%M)
DB_FILE="$BACKUPS/db-$STAMP.sql.gz"

docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists \
  | gzip -9 > "$DB_FILE.partial"

# Only publish the file once it is whole, so a run killed halfway never leaves
# something that looks like a usable backup.
mv "$DB_FILE.partial" "$DB_FILE"

SIZE=$(du -h "$DB_FILE" | cut -f1)
echo "$(date -Is) database -> $DB_FILE ($SIZE)"

# A dump that cannot be read is not a backup. Checking the gzip stream catches
# a truncated or corrupt write straight away.
if ! gzip -t "$DB_FILE"; then
    echo "$(date -Is) ERROR: $DB_FILE failed its integrity check" >&2
    exit 1
fi

find "$BACKUPS" -name 'db-*.sql.gz' -mtime "+$KEEP_DB_DAYS" -delete

# Attachments, on Mondays.
if [ "$(date +%u)" = "1" ] || [ "${FORCE_MEDIA:-0}" = "1" ]; then
    MEDIA_FILE="$BACKUPS/media-$STAMP.tar.gz"
    tar -czf "$MEDIA_FILE.partial" -C "$ROOT" media
    mv "$MEDIA_FILE.partial" "$MEDIA_FILE"
    echo "$(date -Is) media -> $MEDIA_FILE ($(du -h "$MEDIA_FILE" | cut -f1))"
    find "$BACKUPS" -name 'media-*.tar.gz' -mtime "+$((KEEP_MEDIA_WEEKS * 7))" -delete
fi

echo "$(date -Is) backup finished, $(find "$BACKUPS" -type f | wc -l) archive(s) on disk"
