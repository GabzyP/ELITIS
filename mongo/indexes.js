// Koleksi dan indeks MongoDB ELITIS (PRD §6.2)

const targetDbName = (typeof process !== "undefined" && process.env && process.env.MONGO_DB) || "elitis";
const targetDb = db.getSiblingDB(targetDbName);

const collections = ["game_metadata", "raw_metadata", "game_media", "etl_logs"];
const existing = targetDb.getCollectionNames();
for (const name of collections) {
  if (!existing.includes(name)) {
    targetDb.createCollection(name);
  }
}

// game_metadata: cohort Indie ditentukan dari tags
targetDb.game_metadata.createIndex({ app_id: 1 }, { unique: true, name: "uq_game_metadata_app_id" });
targetDb.game_metadata.createIndex({ tags: 1 }, { name: "idx_game_metadata_tags" });

// raw_metadata: dokumen asli apa adanya untuk ketertelusuran
targetDb.raw_metadata.createIndex({ app_id: 1 }, { name: "idx_raw_metadata_app_id" });

// game_media: hasil enrichment media Steam (D-4)
targetDb.game_media.createIndex({ app_id: 1 }, { unique: true, name: "uq_game_media_app_id" });

// etl_logs: satu dokumen per run per tahap
targetDb.etl_logs.createIndex({ run_id: 1 }, { name: "idx_etl_logs_run_id" });
targetDb.etl_logs.createIndex({ started_at: -1 }, { name: "idx_etl_logs_started_at" });
