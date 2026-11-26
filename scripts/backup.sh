#!/usr/bin/env bash
# Skrip Backup PostgreSQL & MongoDB ELITIS (via docker compose exec + cp)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="${1:-$PROJECT_ROOT/backups}"
mkdir -p "$BACKUP_DIR"

cd "$PROJECT_ROOT"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
PG_OUT="$BACKUP_DIR/postgres_${TIMESTAMP}.sql"
MONGO_DUMP_OUT="$BACKUP_DIR/mongo_${TIMESTAMP}"
META_EXPORT_OUT="$BACKUP_DIR/game_metadata.json"
MEDIA_EXPORT_OUT="$BACKUP_DIR/game_media.json"

echo "[backup] Memulai backup ELITIS (${TIMESTAMP}) via docker compose..."

# 1. PostgreSQL pg_dump (tanpa --create agar aman di-restore ke DB uji)
docker compose exec -T postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges -f /tmp/elitis_pg_backup.sql'
docker compose cp postgres:/tmp/elitis_pg_backup.sql "$PG_OUT"
docker compose exec -T postgres rm -f /tmp/elitis_pg_backup.sql

# 2. MongoDB mongodump ke backups/mongo_<timestamp>/
docker compose exec -T mongo sh -c 'rm -rf /tmp/elitis_mongodump && mongodump --db="$MONGO_DB" --out=/tmp/elitis_mongodump --quiet'
MONGO_DB_NAME="$(docker compose exec -T mongo sh -c 'printf "%s" "$MONGO_DB"')"
docker compose cp "mongo:/tmp/elitis_mongodump/${MONGO_DB_NAME}" "$MONGO_DUMP_OUT"
docker compose exec -T mongo rm -rf /tmp/elitis_mongodump

# 3. MongoDB mongoexport game_metadata dan game_media
docker compose exec -T mongo sh -c 'mongoexport --db="$MONGO_DB" --collection=game_metadata --out=/tmp/elitis_game_metadata.json --quiet'
docker compose cp mongo:/tmp/elitis_game_metadata.json "$META_EXPORT_OUT"
docker compose exec -T mongo rm -f /tmp/elitis_game_metadata.json

docker compose exec -T mongo sh -c 'mongoexport --db="$MONGO_DB" --collection=game_media --out=/tmp/elitis_game_media.json --quiet'
docker compose cp mongo:/tmp/elitis_game_media.json "$MEDIA_EXPORT_OUT"
docker compose exec -T mongo rm -f /tmp/elitis_game_media.json

echo "[backup] Selesai:"
echo "  - PostgreSQL dump : $PG_OUT"
echo "  - MongoDB dump    : $MONGO_DUMP_OUT"
echo "  - game_metadata   : $META_EXPORT_OUT"
echo "  - game_media      : $MEDIA_EXPORT_OUT"
