#!/bin/bash
# Install the pet's LaunchAgents for the current user (meant to be the standard user "pet", see CLAUDE.md):
# the web service (restarts on crash, starts at login) and the daily backup. Ollama's agent is set up by setup_mac_mini.sh.
# Usage: scripts/install_services.sh [--dry-run] [--data-dir DIR] [--backup-dir DIR]
# Default data dir is the production one, ~/Library/Application Support/CuriosityPet (CLAUDE.md hard constraint 5).
set -euo pipefail
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$HOME/Library/Application Support/CuriosityPet"
BACKUP_DIR="$HOME/pet-backups"
LOG_DIR="$HOME/Library/Logs/CuriosityPet"
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --data-dir) DATA_DIR="$2"; shift ;;
    --backup-dir) BACKUP_DIR="$2"; shift ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
  shift
done
UV="$(command -v uv)"
AGENTS="$HOME/Library/LaunchAgents"
for name in server backup; do
  src="$PROJECT/scripts/launchd/com.curiositypet.$name.plist.template"
  out="$(sed -e "s#__UV__#$UV#g" -e "s#__PROJECT__#$PROJECT#g" -e "s#__DATA_DIR__#$DATA_DIR#g" \
             -e "s#__BACKUP_DIR__#$BACKUP_DIR#g" -e "s#__LOG_DIR__#$LOG_DIR#g" "$src")"
  if [ "$DRY" = 1 ]; then
    echo "== would write $AGENTS/com.curiositypet.$name.plist"; echo "$out"
  else
    mkdir -p "$AGENTS" "$LOG_DIR" "$DATA_DIR"
    echo "$out" > "$AGENTS/com.curiositypet.$name.plist"
    plutil -lint "$AGENTS/com.curiositypet.$name.plist" >/dev/null
    launchctl bootout "gui/$(id -u)/com.curiositypet.$name" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$AGENTS/com.curiositypet.$name.plist"
    echo "installed com.curiositypet.$name"
  fi
done
