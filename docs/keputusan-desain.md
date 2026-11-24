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

## T4 — Pertahanan Definisi Kohort D-1 & Pembangunan Ulang Sampel `recommendations`
- **Definisi kohort D-1 dipertahankan ketat:** Meskipun beberapa game indie populer (`294100`, `413150`, `105600`, `1145360`) memiliki `"tags": []` pada `games_metadata.json` sumber Kaggle sehingga otomatis tidak masuk kohort D-1, filter kohort (`tags` memuat persis `"Indie"`) **tidak dilonggarkan** maupun di-override secara manual demi menjaga satu sumber kebenaran dari MongoDB.
- **Metode campuran untuk `data/samples/recommendations.csv`:** Karena `recommendations.csv` tidak terurut selaras dengan `games.csv` (baris kohort Indie pertama baru muncul di baris data ke-1.512), sampel `data/samples/recommendations.csv` dibangun ulang dengan menggabungkan 1.000 baris teratas ditambah seluruh baris kohort Indie dari 200.000 baris pertama `data/incoming/recommendations.csv` (476 baris, tanpa duplikat `review_id`, header tetap di baris pertama). Keputusan ini memungkinkan pengujian `--sample` membuktikan pemuatan baris kohort, integritas FK, dan idempotensi tanpa mengubah kode ETL maupun definisi D-1.

## T5 — Konversi `game_stats` Menjadi `MATERIALIZED VIEW`
- **Alasan & bukti `EXPLAIN ANALYZE` pada data penuh (`games` = 27.957 baris, `recommendations` = 10.129.675 baris):**
  - Hitung jumlah hidden gem (`SELECT COUNT(*) FROM game_stats WHERE is_hidden_gem = TRUE`): `112,748 ms` (memakai `Index Only Scan` pada `idx_rec_app`).
  - Daftar hidden gem (`WHERE is_hidden_gem = TRUE ORDER BY positive_ratio DESC, total_reviews DESC LIMIT 20`): **`1.810,589 ms`** (cold) dan **`1.867,537 ms`** (warm cache) karena PostgreSQL melakukan `Seq Scan on recommendations` (10.129.675 baris) untuk menghitung `recommended_share` dan `avg_hours_played`.
  - Top 10 game (`ORDER BY total_recommendations DESC LIMIT 10`): **`7.988,013 ms`** (`7,99` detik) dengan `Hash Right Join` penuh atas `10.129.675` baris `recommendations`.
- **Keputusan:** Karena query representatif dasbor melebihi batas `1 detik` (PRD §6.1) sedangkan dasbor me-refresh setiap `5 detik`, `game_stats` dikonversi dari `VIEW` biasa menjadi **`MATERIALIZED VIEW`** dengan nama dan 14 kolom yang sama persis (definisi `is_hidden_gem` tetap tunggal di `sql/schema.sql`), disertai indeks `idx_game_stats_app_id` (UNIQUE) dan `idx_game_stats_hidden_gem`.
- **Kewajiban tahap lanjutan (T4/T7/T8):**
  - Setiap tahap yang mengubah `games` atau `recommendations` — khususnya **`live_polling` (T7)** dan **`replay` per batch (T8)**, serta setelah pemuatan `games`/`recommendations` — **wajib** menjalankan `REFRESH MATERIALIZED VIEW CONCURRENTLY game_stats;` (atau `REFRESH MATERIALIZED VIEW game_stats;`) agar data dasbor tetap mutakhir.
