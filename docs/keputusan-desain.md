# Keputusan Desain Teknis — ELITIS

Catatan ringkas keputusan teknis yang diambil selama pengerjaan proyek.

## T0 — Kerangka Repositori
- **`APScheduler>=3.10.4,<4.0.0` di `requirements.txt`:** Membatasi ke seri 3.x agar kompatibel dengan API stabil (`BlockingScheduler`/`BackgroundScheduler`) dan tidak terkena perubahan besar di versi 4.x.
- **`.gitignore`:** Menambahkan aturan standar Python (`__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.venv/`), hasil dump backup (`backups/*.sql`, `backups/*.zip`, `backups/mongo/`), serta mempertahankan aturan awal untuk `data/incoming/`, `.env`, dan dokumen instruksi lokal.
- **Skrip `scripts/backup.ps1` & `scripts/restore.ps1`:** Dipilih ekstensi `.ps1` mengikuti lingkungan kerja Windows (PowerShell); implementasi penuh dikerjakan pada T10.

## Rekonsiliasi Eksplorasi Dataset (Fase 1 vs PRD §2)
- **Status verifikasi berhasil (tidak ada selisih terhadap PRD §2):**
  - **Header keempat berkas:** nama dan urutan kolom pada `games.csv`, `users.csv`, `recommendations.csv`, serta kunci dokumen `games_metadata.json` cocok seluruhnya dengan PRD §2.1–2.2; rencana pemetaan kolom pada PRD §2.2 digunakan apa adanya tanpa perubahan.
  - **Format `games_metadata.json` terkonfirmasi JSON Lines:** satu objek JSON per baris (bukan array JSON), sehingga parser ETL akan membaca berkas per baris.
  - **Skala `positive_ratio` terverifikasi 0–100:** rentang 0 sampai 100 di seluruh 50.872 baris `games.csv` (tanpa nilai kosong), sehingga transformasi `÷ 100` ke `NUMERIC(5,4)` (0–1) tetap berlaku.
  - **Penulisan tag `"Indie"` terkonfirmasi:** tertulis persis `"Indie"` (I kapital) pada array `tags`, sesuai kriteria pencocokan persis kohort D-1.
  - **9 nilai `rating` terdaftar:** `Positive`, `Very Positive`, `Mixed`, `Mostly Positive`, `Mostly Negative`, `Overwhelmingly Positive`, `Negative`, `Very Negative`, `Overwhelmingly Negative` (total 50.872 baris, tanpa nilai kosong), disimpan apa adanya ke `rating_category`.
  - **Deskripsi kosong & encoding UTF-8:** dokumen dengan `"description": ""` memang ada (mis. `app_id` 22364), dan berkas mengandung karakter non-ASCII (`™`, `®`), sehingga seluruh berkas sumber wajib dibaca dengan encoding `UTF-8` secara eksplisit.
