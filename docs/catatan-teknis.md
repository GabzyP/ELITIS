# Catatan Teknis — ELITIS

Catatan kendala teknis, hasil verifikasi, dan solusi selama pengembangan.

## Encoding UTF-8 dan Mojibake di PowerShell Windows
- **Temuan:** Berkas sumber Kaggle (`games_metadata.json`) mengandung karakter non-ASCII seperti `™` dan `®`. Terminal PowerShell pada Windows menampilkannya sebagai mojibake (misalnya `™` menjadi `â„¢`) karena code page konsol bukan UTF-8.
- **Dampak & Penanganan:** Ini murni masalah tampilan konsol, bukan kerusakan data. Seluruh modul ETL (`extract.py`, `transform.py`) membaca berkas sumber dengan parameter `encoding='utf-8'` secara eksplisit sehingga karakter tersebut tersimpan benar di MongoDB dan dapat ditampilkan dengan tepat di dasbor Streamlit. Pembuatan sampel (`data/samples/`) menggunakan `head` di Git Bash (bukan `Set-Content` PowerShell) agar byte disalin apa adanya tanpa transkode.

## Koneksi PostgreSQL: Port 5434 dan Konflik Layanan Lokal
- **Temuan:** Mesin pengembangan menjalankan dua instance PostgreSQL lokal Windows (postgresql-x64-17 dan -18) yang mengikat port 5432, sehingga container Docker yang di-expose ke `localhost:5432` mengalami konflik.
- **Penanganan:** `PG_PORT` di `.env` diubah menjadi `5434`; `docker-compose.yml` memetakan `${PG_PORT}:5432`. Seluruh koneksi dari kode Python (`config.py`) dan skrip backup/restore membaca `PG_PORT` dari `.env`.

## Volume Docker untuk Persistensi Data
- **Desain:** `docker-compose.yml` mendefinisikan named volume `postgres_data` dan `mongo_data` agar data kedua database bertahan melebihi siklus hidup container (`docker compose down` tanpa `-v` tidak menghapus data). Volume hanya dihapus secara eksplisit dengan `docker compose down -v` atau `docker volume rm`.
- **Implikasi backup:** `scripts/backup.ps1` dan `scripts/backup.sh` membuat dump menggunakan `pg_dump` dan `mongodump` dari container yang sedang berjalan sehingga tidak bergantung pada path volume di host.

## Sampel & Sumber Data `recommendations.csv`
- **Game indie populer bertags kosong di sumber:** Pada berkas sumber Kaggle `games_metadata.json`, beberapa game indie populer seperti `294100` (RimWorld), `413150` (Stardew Valley), `105600` (Terraria), dan `1145360` (Hades) memiliki array `"tags": []` (kosong). Akibatnya, game-game tersebut berada di luar kohort D-1 (`tags` mengandung `"Indie"`), dan seluruh baris rekomendasinya dibuang dengan alasan `not_in_cohort`.
- **`recommendations.csv` tidak terurut selaras dengan `games.csv`:** Pada 1.000 baris pertama `recommendations.csv` (yang sebelumnya diambil menjadi sampel awal), tidak satu pun `app_id` termasuk dalam kohort Indie. Pemeriksaan 200.000 baris awal `data/incoming/recommendations.csv` menemukan baris kohort Indie pertama baru muncul di baris data ke-1.512 (`app_id=1766740`, `review_id=1511`), dengan total 476 baris kohort di dalam 200.000 baris pertama.
- **Penanganan:** Sampel `data/samples/recommendations.csv` dibangun ulang menggunakan metode campuran (1.000 baris teratas + seluruh 476 baris kohort Indie dari 200.000 baris pertama `data/incoming/recommendations.csv`, tanpa duplikat `review_id`) agar pengujian `--sample` dapat memverifikasi pemuatan baris kohort sekaligus pembuangan `not_in_cohort`.

## Keterbatasan `recommendations.total` pada Steam Store API `appdetails`
- **Temuan saat live polling (`--stage polling --limit 10`):** Pada seluruh 10 game D-4 yang diuji (`490100`, `587310`, `676130`, `797570`, `1511140`, `1986060`, `2092330`, `497690`, `652340`, `1131410`), respons `https://store.steampowered.com/api/appdetails?appids=<app_id>&cc=us&l=english` tidak menyertakan objek `recommendations.total` (`recommendations` bernilai `null`/tidak ada, `no_steam_recommendations=10`), sedangkan `price_overview.final` (atau `is_free: true` untuk game gratis seperti `587310`) tersedia.
- **Dampak & Penanganan:** `live_polling.py` tetap mencatat `price_usd` ke `live_updates` dan memperbarui `games.price_usd` + `games.updated_at`, sementara kolom `live_updates.steam_recommendations` diisi `NULL` bila API tidak menyediakannya (sesuai skema §6.1 dan A-3), tanpa menimpa `games.total_reviews`.
