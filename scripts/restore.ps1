# Skrip Restore ke Database Uji ELITIS (TIDAK pernah menimpa database produksi)
param(
    [string]$BackupDir = "backups",
    [string]$PgSqlFile = "",
    [string]$MongoDumpDir = ""
)

$ErrorActionPreference = "Stop"

$PgTestDb = "elitis_restore_test"
$MongoTestDb = "elitis_mongo_restore_test"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    $TargetDir = Join-Path $ProjectRoot $BackupDir

    if (-not $PgSqlFile) {
        $LatestSql = Get-ChildItem -Path $TargetDir -Filter "postgres_*.sql" | Sort-Object Name -Descending | Select-Object -First 1
        if (-not $LatestSql) { throw "Tidak ada file postgres_*.sql di $TargetDir" }
        $PgSqlFile = $LatestSql.FullName
    }
    if (-not $MongoDumpDir) {
        $LatestMongo = Get-ChildItem -Path $TargetDir -Directory -Filter "mongo_*" | Sort-Object Name -Descending | Select-Object -First 1
        if (-not $LatestMongo) { throw "Tidak ada direktori mongo_* di $TargetDir" }
        $MongoDumpDir = $LatestMongo.FullName
    }

    Write-Host "[restore] PostgreSQL dump : $PgSqlFile -> DB uji '$PgTestDb'"
    Write-Host "[restore] MongoDB dump    : $MongoDumpDir -> DB uji '$MongoTestDb'"

    # 1. Restore PostgreSQL HANYA ke elitis_restore_test
    @"
DROP DATABASE IF EXISTS $PgTestDb WITH (FORCE);
CREATE DATABASE $PgTestDb;
"@ | docker compose exec -T postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres'
    if ($LASTEXITCODE -ne 0) { throw "Gagal membuat ulang DB uji PostgreSQL $PgTestDb" }

    docker compose cp $PgSqlFile postgres:/tmp/elitis_restore.sql
    if ($LASTEXITCODE -ne 0) { throw "Gagal menyalin dump SQL ke container postgres" }

    docker compose exec -T -e "TARGET_DB=$PgTestDb" postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$TARGET_DB" -f /tmp/elitis_restore.sql > /dev/null'
    if ($LASTEXITCODE -ne 0) { throw "psql restore ke $PgTestDb gagal" }
    docker compose exec -T postgres rm -f /tmp/elitis_restore.sql

    # Verifikasi game_stats di DB uji (REFRESH jika kosong)
    $TestGsCount = ("SELECT COUNT(*) FROM game_stats;" | docker compose exec -T -e "TARGET_DB=$PgTestDb" postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -t -A -U "$POSTGRES_USER" -d "$TARGET_DB"').Trim()
    if ([int]$TestGsCount -eq 0) {
        Write-Host "[restore] game_stats di $PgTestDb kosong; menjalankan REFRESH MATERIALIZED VIEW game_stats..."
        "REFRESH MATERIALIZED VIEW game_stats;" | docker compose exec -T -e "TARGET_DB=$PgTestDb" postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$TARGET_DB"'
        if ($LASTEXITCODE -ne 0) { throw "REFRESH MATERIALIZED VIEW game_stats gagal" }
    } else {
        Write-Host "[restore] game_stats di $PgTestDb sudah terisi ($TestGsCount baris)."
    }

    # 2. Restore MongoDB HANYA ke elitis_mongo_restore_test
    "db.dropDatabase()" | docker compose exec -T -e "MONGO_TEST_DB=$MongoTestDb" mongo sh -c 'mongosh --quiet "$MONGO_TEST_DB"' > $null
    if ($LASTEXITCODE -ne 0) { throw "Gagal menghapus DB uji MongoDB $MongoTestDb" }
    docker compose exec -T mongo rm -rf /tmp/elitis_mongorestore
    docker compose cp $MongoDumpDir mongo:/tmp/elitis_mongorestore
    if ($LASTEXITCODE -ne 0) { throw "Gagal menyalin dump MongoDB ke container mongo" }
    docker compose exec -T -e "MONGO_TEST_DB=$MongoTestDb" mongo sh -c 'mongorestore --drop --db="$MONGO_TEST_DB" /tmp/elitis_mongorestore --quiet'
    if ($LASTEXITCODE -ne 0) { throw "mongorestore ke $MongoTestDb gagal" }
    docker compose exec -T mongo rm -rf /tmp/elitis_mongorestore

    # 3. Cetak perbandingan jumlah tabel/koleksi produksi vs database uji
    Write-Host "`n=== PERBANDINGAN POSTGRESQL (PRODUKSI vs $PgTestDb) ==="
    $PgQuery = @"
SELECT item || '|' || jumlah FROM (
    SELECT 1 AS ord, 'games' AS item, COUNT(*) AS jumlah FROM games
    UNION ALL SELECT 2, 'users', COUNT(*) FROM users
    UNION ALL SELECT 3, 'recommendations', COUNT(*) FROM recommendations
    UNION ALL SELECT 4, 'live_updates', COUNT(*) FROM live_updates
    UNION ALL SELECT 5, 'replay_buffer', COUNT(*) FROM replay_buffer
    UNION ALL SELECT 6, 'game_stats', COUNT(*) FROM game_stats
    UNION ALL SELECT 7, 'hidden_gems', COUNT(*) FROM game_stats WHERE is_hidden_gem = TRUE
) q ORDER BY ord;
"@
    $ProdPg = $PgQuery | docker compose exec -T postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
    if ($LASTEXITCODE -ne 0) { throw "Query perbandingan PostgreSQL produksi gagal" }
    $TestPg = $PgQuery | docker compose exec -T -e "TARGET_DB=$PgTestDb" postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -t -A -U "$POSTGRES_USER" -d "$TARGET_DB"'
    if ($LASTEXITCODE -ne 0) { throw "Query perbandingan PostgreSQL uji gagal" }

    $TestMap = @{}
    foreach ($line in $TestPg) {
        if ($line -match "^([^|]+)\|(\d+)$") { $TestMap[$Matches[1]] = $Matches[2] }
    }
    Write-Host ("{0,-18} {1,12} {2,12} {3,8}" -f "Tabel/View", "Produksi", "UjiRestore", "Cocok")
    foreach ($line in $ProdPg) {
        if ($line -match "^([^|]+)\|(\d+)$") {
            $k = $Matches[1]; $vProd = $Matches[2]; $vTest = $TestMap[$k]
            $ok = if ($vProd -eq $vTest) { "YA" } else { "TIDAK" }
            Write-Host ("{0,-18} {1,12} {2,12} {3,8}" -f $k, $vProd, $vTest, $ok)
        }
    }

    Write-Host "`n=== PERBANDINGAN MONGODB (PRODUKSI vs $MongoTestDb) ==="
    $MongoCmpJs = @"
const prodDb = db.getSiblingDB(process.env.MONGO_DB || "elitis");
const testDb = db.getSiblingDB("$MongoTestDb");
["game_metadata", "raw_metadata", "game_media", "etl_logs"].forEach(c => {
  const p = prodDb.getCollection(c).countDocuments({});
  const t = testDb.getCollection(c).countDocuments({});
  print("RESULT:" + c + "|" + p + "|" + t + "|" + (p === t ? "YA" : "TIDAK"));
});
"@
    $MongoRows = $MongoCmpJs | docker compose exec -T mongo mongosh --quiet
    if ($LASTEXITCODE -ne 0) { throw "Query perbandingan MongoDB gagal" }
    Write-Host ("{0,-18} {1,12} {2,12} {3,8}" -f "Koleksi", "Produksi", "UjiRestore", "Cocok")
    foreach ($line in $MongoRows) {
        if ($line -match "RESULT:([a-z_]+)\|(\d+)\|(\d+)\|(YA|TIDAK)") {
            Write-Host ("{0,-18} {1,12} {2,12} {3,8}" -f $Matches[1], $Matches[2], $Matches[3], $Matches[4])
        }
    }
}
finally {
    Pop-Location
}
