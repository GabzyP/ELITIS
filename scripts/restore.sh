#!/usr/bin/env bash
# Skrip Restore ke Database Uji ELITIS (TIDAK pernah menimpa database produksi)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="${1:-$PROJECT_ROOT/backups}"
PG_SQL_FILE="${2:-}"
MONGO_DUMP_DIR="${3:-}"

PG_TEST_DB="elitis_restore_test"
MONGO_TEST_DB="elitis_mongo_restore_test"

cd "$PROJECT_ROOT"

if [[ -z "$PG_SQL_FILE" ]]; then
  PG_SQL_FILE="$(ls -1t "$BACKUP_DIR"/postgres_*.sql | head -n1)"
fi
if [[ -z "$MONGO_DUMP_DIR" ]]; then
  MONGO_DUMP_DIR="$(ls -1dt "$BACKUP_DIR"/mongo_* | head -n1)"
fi

echo "[restore] PostgreSQL dump : $PG_SQL_FILE -> DB uji '$PG_TEST_DB'"
echo "[restore] MongoDB dump    : $MONGO_DUMP_DIR -> DB uji '$MONGO_TEST_DB'"

# 1. Restore PostgreSQL HANYA ke elitis_restore_test
docker compose exec -T postgres sh -c "PGPASSWORD=\"\$POSTGRES_PASSWORD\" psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d postgres -c \"DROP DATABASE IF EXISTS $PG_TEST_DB WITH (FORCE);\" -c \"CREATE DATABASE $PG_TEST_DB;\""
docker compose cp "$PG_SQL_FILE" postgres:/tmp/elitis_restore.sql
docker compose exec -T postgres sh -c "PGPASSWORD=\"\$POSTGRES_PASSWORD\" psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d $PG_TEST_DB -f /tmp/elitis_restore.sql > /dev/null"
docker compose exec -T postgres rm -f /tmp/elitis_restore.sql

TEST_GS_COUNT="$(docker compose exec -T postgres sh -c "PGPASSWORD=\"\$POSTGRES_PASSWORD\" psql -t -A -U \"\$POSTGRES_USER\" -d $PG_TEST_DB -c \"SELECT COUNT(*) FROM game_stats;\"" | tr -d '[:space:]')"
if [[ "$TEST_GS_COUNT" -eq 0 ]]; then
  echo "[restore] game_stats di $PG_TEST_DB kosong; menjalankan REFRESH MATERIALIZED VIEW game_stats..."
  docker compose exec -T postgres sh -c "PGPASSWORD=\"\$POSTGRES_PASSWORD\" psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d $PG_TEST_DB -c \"REFRESH MATERIALIZED VIEW game_stats;\""
else
  echo "[restore] game_stats di $PG_TEST_DB sudah terisi ($TEST_GS_COUNT baris)."
fi

# 2. Restore MongoDB HANYA ke elitis_mongo_restore_test
docker compose exec -T mongo sh -c "mongosh --quiet $MONGO_TEST_DB --eval \"db.dropDatabase()\" > /dev/null && rm -rf /tmp/elitis_mongorestore"
docker compose cp "$MONGO_DUMP_DIR" mongo:/tmp/elitis_mongorestore
docker compose exec -T mongo sh -c "mongorestore --drop --db=$MONGO_TEST_DB /tmp/elitis_mongorestore --quiet"
docker compose exec -T mongo rm -rf /tmp/elitis_mongorestore

# 3. Perbandingan jumlah produksi vs uji
echo ""
echo "=== PERBANDINGAN POSTGRESQL (PRODUKSI vs $PG_TEST_DB) ==="
PG_QUERY="SELECT 'games', COUNT(*) FROM games
UNION ALL SELECT 'users', COUNT(*) FROM users
UNION ALL SELECT 'recommendations', COUNT(*) FROM recommendations
UNION ALL SELECT 'live_updates', COUNT(*) FROM live_updates
UNION ALL SELECT 'replay_buffer', COUNT(*) FROM replay_buffer
UNION ALL SELECT 'game_stats', COUNT(*) FROM game_stats
UNION ALL SELECT 'hidden_gems', COUNT(*) FROM game_stats WHERE is_hidden_gem = TRUE;"

echo "--- Produksi ---"
printf '%s\n' "$PG_QUERY" | docker compose exec -T postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -t -A -F "|" -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
echo "--- Uji ($PG_TEST_DB) ---"
printf '%s\n' "$PG_QUERY" | docker compose exec -T postgres sh -c "PGPASSWORD=\"\$POSTGRES_PASSWORD\" psql -t -A -F \"|\" -U \"\$POSTGRES_USER\" -d $PG_TEST_DB"

echo ""
echo "=== PERBANDINGAN MONGODB (PRODUKSI vs $MONGO_TEST_DB) ==="
docker compose exec -T mongo mongosh --quiet <<EOF
const prodDb = db.getSiblingDB(process.env.MONGO_DB || "elitis");
const testDb = db.getSiblingDB("$MONGO_TEST_DB");
["game_metadata", "raw_metadata", "game_media", "etl_logs"].forEach(c => {
  const p = prodDb.getCollection(c).countDocuments({});
  const t = testDb.getCollection(c).countDocuments({});
  print(c + " | prod=" + p + " | test=" + t + " | cocok=" + (p === t ? "YA" : "TIDAK"));
});
EOF
