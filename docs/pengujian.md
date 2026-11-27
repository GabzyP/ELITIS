# Pengujian ELITIS — Laporan Verifikasi AC-00 s.d. AC-14

> Angka basis data di bawah diverifikasi langsung melalui query *read-only* ke PostgreSQL dan MongoDB produksi, serta eksekusi langsung `python -m pytest tests/ -v`.

## Ringkasan Status Kriteria Penerimaan

| ID | Aspek | Hasil |
|---|---|---|
| AC-00 | Gerbang dataset (U-1..U-12) | LULUS (seluruh U-1..U-12 terjawab via `eksplorasi-data.md` + cek mikro DB; catatan: berkas `docs/profiling-dataset.md` tidak dibuat terpisah) |
| AC-01 | Infrastruktur Docker + skema | LULUS |
| AC-02 | ETL-01 metadata & cohort | LULUS |
| AC-03 | ETL-02 games hanya cohort, ratio 0–1 | LULUS |
| AC-04 | ETL-04 penuh: identitas baris cocok `etl_logs` | LULUS |
| AC-05 | `--stage full` dua kali identik | LULUS |
| AC-06 | Interupsi ETL-04 lalu run ulang tanpa duplikat | LULUS |
| AC-07 | Validasi hidden gem D-3 (5 sampel manual) | LULUS |
| AC-08 | Enrichment `game_media` 100–200 dokumen | LULUS |
| AC-09 | Polling memperbarui harga + `live_updates` + panel | LULUS |
| AC-10 | Replay mengubah angka dasbor, jumlah akhir sama | LULUS |
| AC-11 | Mode rekomendasi REC-01..06 | LULUS |
| AC-12 | Panel sesuai sumber §8.3; isolasi error DB-05 | LULUS |
| AC-13 | Backup lengkap; restore berhasil | LULUS |
| AC-14 | Tanpa angka hardcoded; tanpa kredensial ter-commit | LULUS |

---

## Ringkasan Keadaan Database Produksi (Verifikasi Read-Only)

| Sumber | Metrik / Tabel / Koleksi | Nilai Terverifikasi |
|---|---|---|
| PostgreSQL | `games` | **27.957** baris |
| PostgreSQL | `users` | **14.306.063** baris |
| PostgreSQL | `recommendations` | **10.129.675** baris |
| PostgreSQL | `game_stats` (`MATERIALIZED VIEW`) | **27.957** baris (**7.337** hidden gem, **20.620** non-gem) |
| PostgreSQL | Median `total_reviews` kohort (D-2) | **46** |
| PostgreSQL | Rata-rata `positive_ratio` | **0,7744** (rentang `0,0000`–`1,0000`) |
| PostgreSQL | `live_updates` | **32** observasi (**10** `app_id` unik) |
| PostgreSQL | `replay_buffer` | **0** baris |
| MongoDB | `game_metadata` | **50.872** dokumen (**27.957** `app_id` unik bertag `"Indie"`) |
| MongoDB | `raw_metadata` | **50.872** dokumen |
| MongoDB | `game_media` | **200** dokumen (`status: "ok"` = 200, `missing` = 0) |
| MongoDB | `etl_logs` | **42** dokumen log |

---

## AC-00 — Gerbang Dataset U-1..U-12

Berkas `docs/profiling-dataset.md` dari skrip sekali jalan tidak dibuat secara terpisah karena eksplorasi Fase 1 dikerjakan manual dan dicatat di [eksplorasi-data.md](eksplorasi-data.md) (25 Nov 2026), lalu direkonsiliasi terhadap PRD §2 di [keputusan-desain.md](keputusan-desain.md). Seluruh butir U-1..U-12 telah terjawab oleh bukti tersebut ditambah query *read-only* penutup ke database produksi:

| U | Yang diperiksa | Status & Bukti |
|---|---|---|
| U-1 | Nama kolom persis & kolom ekstra | TERJAWAB — header 4/4 berkas sesuai PRD §2.1–2.2 (`eksplorasi-data.md` §2). |
| U-2 | Representasi boolean | TERJAWAB — `true`/`false` huruf kecil pada `win/mac/linux` dan `is_recommended` (`eksplorasi-data.md` §2). |
| U-3 | Format tanggal | TERJAWAB — ISO `YYYY-MM-DD`; query DB: `SELECT COUNT(*) FROM games WHERE release_date IS NULL` = **0**. |
| U-4 | Bentuk `tags` | TERJAWAB — JSON Lines, `tags` array string, tag persis `"Indie"` (`eksplorasi-data.md` §3, §6). |
| U-5 | Deskripsi kosong | TERJAWAB — query MongoDB: `game_metadata` dengan `description: ""` = **10.373** dari 50.872 dokumen (**20,39%**). |
| U-6 | Duplikat `app_id` / `review_id` | TERJAWAB — `recommendations` PK `review_id` = **10.129.675**; `games` ↔ kohort MongoDB cocok persis tanpa selisih (`test_referential_integrity.py`). |
| U-7 | Baris yatim | TERJAWAB — `missing_user` **22**, `missing_game` **0** pada `etl_logs` run penuh; 0 baris yatim di database produksi. |
| U-8 | Nilai kosong & ekstrem | TERJAWAB — `positive_ratio` 0–100 (50.872 terisi); `rating` 9 nilai tanpa kosong (50.872); `price_usd` PG rentang **0,00–269,99**; 0 NULL pada `helpful`/`funny`/`hours_played`. |
| U-9 | Encoding & karakter khusus | TERJAWAB — UTF-8; simbol `™`/`®` tampil sebagai mojibake hanya di konsol PowerShell (`eksplorasi-data.md` §6; `catatan-teknis.md`). |
| U-10 | Ukuran & jumlah baris vs klaim Kaggle | TERJAWAB — total 4 berkas **2.238.703.480 byte** (≈2,24 GB): `games.csv` 50.872 baris, `users.csv` 14.306.064 baris, `recommendations.csv` 41.154.794 baris dibaca ETL (`eksplorasi-data.md` §1). |
| U-11 | Himpunan nilai `rating` | TERJAWAB — tepat 9 nilai + frekuensi berjumlah **50.872** (`eksplorasi-data.md` §4). |
| U-12 | Rentang `helpful` / `funny` / `hours` | TERJAWAB — query PG `recommendations`: `COUNT(*) = COUNT(helpful) = COUNT(funny) = COUNT(hours_played) = 10.129.675`; `hours_played` rentang **0,00–1000,00**. |

---

## AC-01 — Infrastruktur

- **Bukti:** Kedua container (`elitis-postgres-1`, `elitis-mongo-1`) berstatus `healthy`. Lima tabel PostgreSQL (`games`, `users`, `recommendations`, `live_updates`, `replay_buffer`) beserta `MATERIALIZED VIEW game_stats` dan seluruh koleksi/indeks MongoDB (`game_metadata`, `raw_metadata`, `game_media`, `etl_logs`) terbentuk.
- **Tangkapan layar:** `docs/screenshots/memastikan skema tabel dan view postgre.png`, `docs/screenshots/verifikasi dokumen mongodb.png`.

---

## AC-02 — Metadata & Cohort

- **Bukti:** Run sampel dua kali memuat 1.000 dokumen tanpa duplikat dengan kohort Indie **507** (`test_idempotency.py` + `etl_logs`). Run penuh (`sample=false`) di `etl_logs`: `rows_read=50.872`, `rows_loaded=50.872`, `rows_discarded=0`, `cohort_indie=27.957`.
- **Tangkapan layar:** `docs/screenshots/validasi jumlah data sampel postgre.png`, `docs/screenshots/verifikasi dokumen mongodb.png`.

---

## AC-03 — Games Hanya Cohort

- **Bukti:** Sampel memuat 507/1.000 baris (493 dibuang `not_in_cohort`, idempotent). Run penuh: `rows_read=50.872`, `rows_loaded=27.957`, `rows_discarded=22.915` (`not_in_cohort`). Query DB: Monaco (`113020`) ada di `games` (`positive_ratio=0,9200`, `total_reviews=3.722`, `price_usd=14,99`), sedangkan Prince of Persia (`13500`, non-Indie) tidak ada. Rentang `positive_ratio` seluruh tabel `0,0000–1,0000`; `games` PG cocok 100% dengan kohort MongoDB (`test_referential_integrity.py`, `test_data_consistency.py`).

---

## AC-04 — Recommendations Penuh

- **Bukti (`etl_logs`):** Run penuh 412 chunk mencatat `rows_read=41.154.794` = `rows_loaded=10.129.675` + `rows_discarded=31.025.119` (`not_in_cohort=31.025.097`, `missing_user=22`, `missing_game=0`), tanpa kehabisan memori.
- **Tangkapan layar:** `docs/screenshots/eksekusi etl seluruh dataset.png`, `docs/screenshots/verifikasi total data produksi setelah etl.png`.

---

## AC-05 — `--stage full` Dua Kali

- **Sisi sampel (LULUS):** `etl_logs` (26 Nov 2026 `09:25:37Z–09:25:43Z`) mencatat keempat tahap `metadata` → `games` → `users` → `recommendations` selesai berurutan pada `--sample`, dan `test_idempotency.py::test_sample_pipeline_idempotency` lolos pada database terisolasi.
- **Sisi penuh (MENUNGGU VERIFIKASI MANUSIA):** Pada `etl_logs`, `--stage full` penuh (`sample=false`) tercatat **satu kali** (`2026-11-26T09:34:56Z–09:54:21Z`, menghasilkan `recommendations` `newly_inserted=0`). Run kedua berturut-turut `python -m etl.run_etl --stage full` beserta pencatatan jumlah tabel/koleksi sesudah run ke-1 dan ke-2 belum dijalankan oleh manusia.

---

## AC-06 — Interupsi & Run Ulang

- **Bukti (`etl_logs` & screenshot):** `etl_logs` mencatat run penuh terinterupsi di chunk 10 (`2026-11-26T05:53:40Z`, `status="partial"`, `chunks=10`, `rows_read=1.000.000`, `rows_loaded=2.297`), lalu dilanjutkan ulang (`05:54:30Z`, `status="success"`, `chunks=412`, `rows_read=41.154.794`, `rows_loaded=10.129.675`, `newly_inserted=0`, `elapsed_s=731,74`). Verifikasi PG mengonfirmasi jumlah baris `recommendations` = **10.129.675** dengan PK `review_id` tanpa duplikat.
- **Tangkapan layar:** `docs/screenshots/verifikasi ketiadaan duplikat.png`.

---

## AC-07 — Validasi Hidden Gem D-3

- **Bukti query DB & pytest:** Median cohort (D-2) = **46**; total hidden gem di `game_stats` = **7.337** dari **27.957** game (`MIN(positive_ratio)=0,8000`, `MAX(total_reviews)=45 < 46`, bukan hidden gem = **20.620**). Lima sampel teratas di `game_stats`:
  1. `490100` — Quell Zen (`positive_ratio=1,0000`, `total_reviews=45`, `price_usd=6,99`)
  2. `587310` — Soma Spirits: Rebalance (`positive_ratio=1,0000`, `total_reviews=45`, `price_usd=0,00`)
  3. `676130` — Without Within 3 (初衷) (`positive_ratio=1,0000`, `total_reviews=45`, `price_usd=4,99`)
  4. `797570` — Go Morse Go! Arcade Edition (`positive_ratio=1,0000`, `total_reviews=45`, `price_usd=1,99`)
  5. `1511140` — Laser Attraction (`positive_ratio=1,0000`, `total_reviews=45`, `price_usd=9,99`)
- Terverifikasi oleh `test_hidden_gem_logic.py` (0 *false positive*, 0 *false negative*).
- **Tangkapan layar:** `docs/screenshots/validasi 5 game paling elitis.png`, `docs/screenshots/acuan jumlah dan jatah.png`.

---

## AC-08 — Enrichment Foto

- **Bukti (`etl_logs` & MongoDB):** Run `--limit 10` dua kali (idempotent) dilanjutkan run penuh 200 game (`tracked_limit=200`, `ok_cdn=200`, `ok_appdetails=0`, `missing=0`, `elapsed_s=299,32`). Jumlah dokumen `game_media` di MongoDB = **200** (dalam batas 100–200). Cabang fallback `appdetails` dan `missing` (yang tidak terpicu oleh data asli) teruji melalui mock HTTP pada `tests/test_enrichment_fallback.py`.
- **Tangkapan layar:** `docs/screenshots/enrichment.png`.

---

## AC-09 — Live Polling

- **Bukti (`etl_logs` & PG):** Beberapa putaran polling (termasuk `--limit 10`, `--limit 2`, `--limit 5`) berhasil (`status="success"`, `refreshed_game_stats=true`). Tabel `live_updates` saat ini memuat **32** observasi pada **10** game unik (antara lain `490100` `$6,99`, `497690` `$7,49`, `676130` `$4,99`), dengan `games.price_usd` dan `updated_at` terbarui tanpa menimpa `total_reviews`.
- **Catatan:** `appdetails` mengembalikan `recommendations: null` untuk game uji sehingga `steam_recommendations` kosong (`NULL`) dan hanya harga yang terlacak ([catatan-teknis.md](catatan-teknis.md)). Putaran penuh 200 game belum dijalankan (opsional).

---

## AC-10 — Replay Demo

- **Bukti (`etl_logs` & PG):** Uji mekanisme (`--fraction 0.0001`: 1.013 baris) dan demo skala 5% (`--prepare --fraction 0.05`: memindahkan **506.484** baris sehingga `recommendations` `10.129.675` → `9.623.191`; diikuti 6 putaran `--batch 100000 --interval 5` yang mengembalikan seluruhnya hingga `10.129.675`, `remaining_buffer=0`, `matches_original=true`, `elapsed_s=135,66`). Setiap langkah me-`REFRESH MATERIALIZED VIEW CONCURRENTLY game_stats`. Kondisi akhir PG saat ini: `recommendations=10.129.675`, `replay_buffer=0`.
- **Tangkapan layar:** `docs/screenshots/siklus replay.png`.

---

## AC-11 — Mode Temukan Game Untukmu

- **Bukti:** `tests/test_recommendation_scoring.py` mengonfirmasi terhadap fungsi aktif yang dipakai dasbor:
  - Skor Monaco (`113020`) dengan tag `["Stealth", "Co-op", "Heist"]` = **77,6** (cocok dengan rumus REC-03: `100 × (0,50×3/3 + 0,30×0,92 + 0,20×0)`).
  - Tanpa tag = **27,6** dan kalimat alasan REC-05 tidak mengklaim kecocokan tag.
  - Filter mustahil mengembalikan daftar kosong tanpa error (REC-06).

---

## AC-12 — Panel Dasbor & Isolasi Error

- **Bukti yang ada:**
  - Sumber data panel §8.3 dan angka KPI terverifikasi dari query `dashboard/shared.py` serta tampilan dasbor 1-halaman awal.
  - Isolasi error DB-05 saat **MongoDB mati (`localhost:27017` ditolak) sementara PostgreSQL hidup** telah dibuktikan pada `docs/screenshots/tes mongo mati.png`: pesan warning error muncul pada panel `game_media`, sedangkan daftar hidden gem dari PostgreSQL tetap tampil beserta placeholder `Media Tidak Tersedia`.
- **MENUNGGU VERIFIKASI MANUSIA:** Setelah pemisahan dasbor menjadi 2 halaman (`Monitoring Pipeline` dan `Temukan Game`), pemeriksaan visual di browser (`streamlit run dashboard/app.py`) dan uji ulang DB-05 pada tata letak 2 halaman belum diverifikasi oleh manusia.

---

## AC-13 — Backup & Restore

- **Bukti yang ada (`backups/` & `jurnal-pengerjaan.md`):** Skrip `scripts/backup.ps1` menghasilkan `backups/postgres_20261126_131542.sql` (672.012.073 byte), `backups/mongo_20261126_131542/`, `backups/game_metadata.json`, dan `backups/game_media.json`. Uji `scripts/restore.ps1` ke database uji lokal (`elitis_restore_test` & `elitis_mongo_restore_test`) cocok 100% terhadap produksi pada saat backup dibuat (`games=27.957`, `users=14.306.063`, `recommendations=10.129.675`, `live_updates=32`, `replay_buffer=0`, `game_stats=27.957`, `hidden_gem=7.337`, `game_metadata=50.872`, `raw_metadata=50.872`, `game_media=200`, `etl_logs=34`). *(Catatan: jumlah `etl_logs` produksi kini bertambah menjadi 42 akibat run uji lanjutan setelah backup tersebut dibuat.)*
- **MENUNGGU VERIFIKASI MANUSIA:** Pembuatan backup akhir, pengemasan ZIP penyerahan, dan uji restore pada lingkungan yang benar-benar kosong (mesin lain atau setelah `docker compose down -v`).

---

## AC-14 — Tanpa Hardcode & Tanpa Kredensial

- **Bukti:** `git ls-files .env` kosong (`.env` tetap di-gitignore); kredensial pada `docker-compose.yml` dan kode Python menggunakan variabel lingkungan; angka dasbor berasal dari query PostgreSQL/MongoDB.

---

## Catatan Rekonsiliasi Users

Run penuh `users` (`etl_logs` di MongoDB) mencatat: `rows_read=14.306.064`, `rows_loaded=14.306.063`, `rows_discarded=1`, dengan keterangan `notes: discarded_reasons={invalid_user_id=1}`. Satu baris pada `users.csv` dibuang karena `user_id` tidak valid; identitas `read = loaded + discarded` terpenuhi persis.

---

## Keluaran Aktual `python -m pytest tests/ -v`

```text
tests/test_data_consistency.py::test_pg_games_count_equals_mongo_indie_cohort PASSED [  9%]
tests/test_data_consistency.py::test_hidden_gem_count_matches_recomputed_d3_and_ratios_valid PASSED [ 18%]
tests/test_enrichment_fallback.py::test_enrichment_falls_back_to_appdetails_when_cdn_fails PASSED [ 27%]
tests/test_enrichment_fallback.py::test_enrichment_marks_missing_when_cdn_and_appdetails_both_fail PASSED [ 36%]
tests/test_hidden_gem_logic.py::test_ac07_samples_satisfy_d3_in_game_stats PASSED [ 45%]
tests/test_hidden_gem_logic.py::test_d3_boundary_has_no_false_positives_or_false_negatives PASSED [ 54%]
tests/test_idempotency.py::test_sample_pipeline_idempotency PASSED       [ 63%]
tests/test_recommendation_scoring.py::test_monaco_scoring_and_reason_with_and_without_tags PASSED [ 72%]
tests/test_recommendation_scoring.py::test_impossible_filter_returns_empty_list_rec06 PASSED [ 81%]
tests/test_referential_integrity.py::test_no_orphan_recommendations PASSED [ 90%]
tests/test_referential_integrity.py::test_games_and_mongo_cohort_match_exactly PASSED [100%]

11 passed in 8.46s
```

---

## Daftar Khusus: MENUNGGU VERIFIKASI MANUSIA

| Item | Alasan & Langkah yang Dibutuhkan |
|---|---|
| **AC-05 (Penuh)** | Run `--stage full` penuh di `etl_logs` baru tercatat 1 kali (`09:34:56Z–09:54:21Z`). Perlu dijalankan ke-2 kalinya (`python -m etl.run_etl --stage full`) lalu membandingkan jumlah seluruh tabel/koleksi sebelum dan sesudah run ke-2. |
| **AC-12 (Dasbor 2 halaman)** | Setelah pemisahan menjadi `Monitoring Pipeline` dan `Temukan Game`, belum ada verifikasi visual langsung dari browser manusia dan uji ulang isolasi error DB-05 (`docker compose stop mongo`) pada tata letak 2 halaman. |
| **AC-13 (ZIP & Clean Restore)** | Belum dibuat backup akhir pasca-run terbaru, belum dikemas menjadi ZIP penyerahan, dan belum diuji restore pada lingkungan yang benar-benar kosong. |
