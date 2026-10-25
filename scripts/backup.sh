#!/bin/bash
# Back up the pet's data directory: a consistent copy of pet.db (sqlite .backup, safe while the server runs), settings,
# skins, reports and reviewed library files. The library index and its dumps are not copied (rebuild with pet-library).
# Keeps the newest KEEP backups. Usage: scripts/backup.sh [DATA_DIR] [BACKUP_DIR]
set -euo pipefail
DATA_DIR="${1:-${PET_DATA_DIR:-$HOME/pet-data-dev}}"
BACKUP_DIR="${2:-$HOME/pet-backups}"
KEEP="${KEEP:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_DIR/$STAMP"
mkdir -p "$DEST"
if [ -f "$DATA_DIR/pet.db" ]; then
  sqlite3 "$DATA_DIR/pet.db" ".backup '$DEST/pet.db'"
  sqlite3 "$DEST/pet.db" "PRAGMA integrity_check;" | grep -qx ok
fi
[ -f "$DATA_DIR/settings.json" ] && cp "$DATA_DIR/settings.json" "$DEST/"
for d in "$DATA_DIR"/skin "$DATA_DIR"/skin-* "$DATA_DIR"/reports "$DATA_DIR"/library/qa; do
  [ -d "$d" ] && cp -R "$d" "$DEST/"
done
chmod -R go-rwx "$DEST"
# Rotate: keep the newest $KEEP
TOTAL="$(ls -1d "$BACKUP_DIR"/2* 2>/dev/null | wc -l | tr -d ' ')"
if [ "$TOTAL" -gt "$KEEP" ]; then
  ls -1d "$BACKUP_DIR"/2* | sort | head -n "$((TOTAL - KEEP))" | while read -r old; do rm -rf -- "$old"; done
fi
echo "backup ok: $DEST"
