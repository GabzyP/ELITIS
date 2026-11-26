# Skrip Backup PostgreSQL & MongoDB ELITIS (via docker compose exec + cp)
param(
    [string]$BackupDir = "backups"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    $TargetDir = Join-Path $ProjectRoot $BackupDir
    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $PgOut = Join-Path $TargetDir "postgres_$Timestamp.sql"
    $MongoDumpOut = Join-Path $TargetDir "mongo_$Timestamp"
    $MetaExportOut = Join-Path $TargetDir "game_metadata.json"
    $MediaExportOut = Join-Path $TargetDir "game_media.json"

    Write-Host "[backup] Memulai backup ELITIS ($Timestamp) via docker compose..."

    # 1. PostgreSQL pg_dump (tanpa --create agar aman di-restore ke DB uji)
    docker compose exec -T postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges -f /tmp/elitis_pg_backup.sql'
    if ($LASTEXITCODE -ne 0) { throw "pg_dump gagal" }
    docker compose cp postgres:/tmp/elitis_pg_backup.sql $PgOut
    if ($LASTEXITCODE -ne 0) { throw "docker compose cp postgres backup gagal" }
    docker compose exec -T postgres rm -f /tmp/elitis_pg_backup.sql

    # 2. MongoDB mongodump ke backups/mongo_<timestamp>/
    docker compose exec -T mongo sh -c 'rm -rf /tmp/elitis_mongodump && mongodump --db="$MONGO_DB" --out=/tmp/elitis_mongodump --quiet'
    if ($LASTEXITCODE -ne 0) { throw "mongodump gagal" }
    $MongoDbName = (docker compose exec -T mongo sh -c 'printf "%s" "$MONGO_DB"').Trim()
    docker compose cp "mongo:/tmp/elitis_mongodump/$MongoDbName" $MongoDumpOut
    if ($LASTEXITCODE -ne 0) { throw "docker compose cp mongodump gagal" }
    docker compose exec -T mongo rm -rf /tmp/elitis_mongodump

    # 3. MongoDB mongoexport game_metadata dan game_media
    docker compose exec -T mongo sh -c 'mongoexport --db="$MONGO_DB" --collection=game_metadata --out=/tmp/elitis_game_metadata.json --quiet'
    if ($LASTEXITCODE -ne 0) { throw "mongoexport game_metadata gagal" }
    docker compose cp mongo:/tmp/elitis_game_metadata.json $MetaExportOut
    docker compose exec -T mongo rm -f /tmp/elitis_game_metadata.json

    docker compose exec -T mongo sh -c 'mongoexport --db="$MONGO_DB" --collection=game_media --out=/tmp/elitis_game_media.json --quiet'
    if ($LASTEXITCODE -ne 0) { throw "mongoexport game_media gagal" }
    docker compose cp mongo:/tmp/elitis_game_media.json $MediaExportOut
    docker compose exec -T mongo rm -f /tmp/elitis_game_media.json

    Write-Host "[backup] Selesai:"
    Write-Host "  - PostgreSQL dump : $PgOut"
    Write-Host "  - MongoDB dump    : $MongoDumpOut"
    Write-Host "  - game_metadata   : $MetaExportOut"
    Write-Host "  - game_media      : $MediaExportOut"
}
finally {
    Pop-Location
}
