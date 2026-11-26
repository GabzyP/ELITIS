# Catatan Teknis — ELITIS

Catatan kendala teknis, hasil verifikasi, dan solusi selama pengembangan.

## Sampel & Sumber Data `recommendations.csv`
- **Game indie populer bertags kosong di sumber:** Pada berkas sumber Kaggle `games_metadata.json`, beberapa game indie populer seperti `294100` (RimWorld), `413150` (Stardew Valley), `105600` (Terraria), dan `1145360` (Hades) memiliki array `"tags": []` (kosong). Akibatnya, game-game tersebut berada di luar kohort D-1 (`tags` mengandung `"Indie"`), dan seluruh baris rekomendasinya dibuang dengan alasan `not_in_cohort`.
- **`recommendations.csv` tidak terurut selaras dengan `games.csv`:** Pada 1.000 baris pertama `recommendations.csv` (yang sebelumnya diambil menjadi sampel awal), tidak satu pun `app_id` termasuk dalam kohort Indie. Pemeriksaan 200.000 baris awal `data/incoming/recommendations.csv` menemukan baris kohort Indie pertama baru muncul di baris data ke-1.512 (`app_id=1766740`, `review_id=1511`), dengan total 476 baris kohort di dalam 200.000 baris pertama.
- **Penanganan:** Sampel `data/samples/recommendations.csv` dibangun ulang menggunakan metode campuran (1.000 baris teratas + seluruh 476 baris kohort Indie dari 200.000 baris pertama `data/incoming/recommendations.csv`, tanpa duplikat `review_id`) agar pengujian `--sample` dapat memverifikasi pemuatan baris kohort sekaligus pembuangan `not_in_cohort`.

## Keterbatasan `recommendations.total` pada Steam Store API `appdetails`
- **Temuan saat live polling (`--stage polling --limit 10`):** Pada seluruh 10 game D-4 yang diuji (`490100`, `587310`, `676130`, `797570`, `1511140`, `1986060`, `2092330`, `497690`, `652340`, `1131410`), respons `https://store.steampowered.com/api/appdetails?appids=<app_id>&cc=us&l=english` tidak menyertakan objek `recommendations.total` (`recommendations` bernilai `null`/tidak ada, `no_steam_recommendations=10`), sedangkan `price_overview.final` (atau `is_free: true` untuk game gratis seperti `587310`) tersedia.
- **Dampak & Penanganan:** `live_polling.py` tetap mencatat `price_usd` ke `live_updates` dan memperbarui `games.price_usd` + `games.updated_at`, sementara kolom `live_updates.steam_recommendations` diisi `NULL` bila API tidak menyediakannya (sesuai skema §6.1 dan A-3), tanpa menimpa `games.total_reviews`.
