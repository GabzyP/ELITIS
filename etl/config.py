"""Konfigurasi aplikasi dan helper koneksi database ELITIS."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.database import Database

if TYPE_CHECKING:
    import psycopg

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    """Konfigurasi runtime yang dimuat dari environment / berkas .env."""

    pg_host: str
    pg_port: int
    pg_db: str
    pg_user: str
    pg_password: str
    mongo_uri: str
    mongo_db: str
    data_incoming_dir: Path
    data_samples_dir: Path
    chunk_size: int
    tracked_limit: int
    polling_interval_minutes: int
    steam_api_delay_seconds: float
    dashboard_refresh_seconds: int


def _resolve_dir(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def get_settings() -> Settings:
    """Muat konfigurasi dari .env (jika ada) dan environment variables."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    return Settings(
        pg_host=os.getenv("PG_HOST", "localhost"),
        pg_port=int(os.getenv("PG_PORT", "5432")),
        pg_db=os.getenv("PG_DB", "elitis"),
        pg_user=os.getenv("PG_USER", "elitis"),
        pg_password=os.getenv("PG_PASSWORD", ""),
        mongo_uri=os.getenv("MONGO_URI", "mongodb://localhost:27017"),
        mongo_db=os.getenv("MONGO_DB", "elitis"),
        data_incoming_dir=_resolve_dir(os.getenv("DATA_INCOMING_DIR", "data/incoming")),
        data_samples_dir=PROJECT_ROOT / "data" / "samples",
        chunk_size=int(os.getenv("CHUNK_SIZE", "100000")),
        tracked_limit=int(os.getenv("TRACKED_LIMIT", "200")),
        polling_interval_minutes=int(os.getenv("POLLING_INTERVAL_MINUTES", "30")),
        steam_api_delay_seconds=float(os.getenv("STEAM_API_DELAY_SECONDS", "1.5")),
        dashboard_refresh_seconds=int(os.getenv("DASHBOARD_REFRESH_SECONDS", "5")),
    )


def get_mongo_client(settings: Settings | None = None) -> MongoClient:
    """Buat instance MongoClient menggunakan MONGO_URI dari konfigurasi."""
    cfg = settings or get_settings()
    return MongoClient(cfg.mongo_uri, serverSelectionTimeoutMS=5000)


def get_mongo_db(settings: Settings | None = None) -> tuple[MongoClient, Database]:
    """Kembalikan tuple (MongoClient, Database) untuk database target ELITIS."""
    cfg = settings or get_settings()
    client = get_mongo_client(cfg)
    return client, client[cfg.mongo_db]


def get_pg_connection(settings: Settings | None = None) -> psycopg.Connection:
    """Buat koneksi PostgreSQL (psycopg v3) dari konfigurasi .env."""
    import psycopg

    cfg = settings or get_settings()
    return psycopg.connect(
        host=cfg.pg_host,
        port=cfg.pg_port,
        dbname=cfg.pg_db,
        user=cfg.pg_user,
        password=cfg.pg_password,
        connect_timeout=10,
    )


def resolve_source_path(filename: str, sample: bool, settings: Settings | None = None) -> Path:
    """Tentukan path berkas sumber berdasarkan mode --sample atau DATA_INCOMING_DIR."""
    cfg = settings or get_settings()
    base_dir = cfg.data_samples_dir if sample else cfg.data_incoming_dir
    return base_dir / filename
