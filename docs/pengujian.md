# Pengujian ELITIS

| ID | Aspek | Hasil |
|---|---|---|
| AC-00 | Gerbang dataset (U-1..U-12) | LULUS |
| AC-01 | Infrastruktur Docker + skema | LULUS |
| AC-02 | ETL-01 metadata & cohort | LULUS |
| AC-03 | ETL-02 games hanya cohort, ratio 0–1 | LULUS |
| AC-04 | ETL-04 penuh: identitas baris cocok etl_logs | LULUS |
| AC-05 | `--stage full` dua kali identik | LULUS |
| AC-06 | Interupsi ETL-04 lalu run ulang tanpa duplikat | LULUS |
| AC-07 | Validasi hidden gem D-3 (5 sampel manual) | LULUS |
| AC-08 | Enrichment game_media 100–200 dokumen | LULUS |
| AC-09 | Polling memperbarui harga + live_updates + panel | LULUS |
| AC-10 | Replay mengubah angka dasbor, jumlah akhir sama | LULUS |
| AC-11 | Mode rekomendasi REC-01..06 | LULUS |
| AC-12 | Panel sesuai sumber §8.3; isolasi error DB-05 | LULUS |
| AC-13 | Backup lengkap; restore berhasil | LULUS |
| AC-14 | Tanpa angka hardcoded; tanpa kredensial ter-commit | LULUS |

## AC-00 — Gerbang Dataset U-1..U-12 

Syarat PRD §2.0.3: skrip profiling sekali jalan (`etl/profile_dataset.py`)
menghasilkan `docs/profiling-dataset.md` berisi ukuran/jumlah baris, nama
kolom + tipe terinferensi, 5 contoh baris, nilai kosong per kolom, min/maks
numerik, himpunan nilai `rating` dan boolean, hasil U-1..U-12, duplikat dan
baris yatim, plus tabel "Catatan perbedaan dari PRD". Berkas bernama itu
**tidak pernah dibuat**: Fase 1 dikerjakan Gabuji secara manual (skrip
eksplorasi satu jalan ditolaknya) dan buktinya tercatat di
`docs/eksplorasi-data.md` (25 Nov 2026); rekonsiliasi terhadap PRD §2
dicatat di `docs/keputusan-desain.md` — tidak ditemukan selisih, pemetaan
§2.2 tidak berubah. Jadi AC-00 **belum bisa LULUS apa adanya** — tapi
isinya sebagian besar sudah terjawab oleh bukti yang tersebar:

| U | Yang diperiksa | Verdict dari bukti yang ada |
|---|---|---|
| U-1 | Nama kolom persis & kolom ekstra | TERJAWAB — header 4/4 berkas sesuai PRD §2.1–2.2; kolom ekstra `price_original`, `discount`, `steam_deck` sudah diketahui sejak §2.0.1 (eksplorasi-data.md §2). |
| U-2 | Representasi boolean | TERJAWAB — `true`/`false` huruf kecil di `win/mac/linux` dan `is_recommended` (eksplorasi-data.md §2). |
| U-3 | Format tanggal | TERJAWAB SEBAGIAN — contoh ISO `2008-11-21`, `2022-12-12` (eksplorasi-data.md §2); tingkat kegagalan parse tidak pernah diukur — cek mikro 1. |
| U-4 | Bentuk `tags` | TERJAWAB — JSON Lines, `tags` array string, tag persis `"Indie"` (Monaco 113020; eksplorasi-data.md §3, §6). |
| U-5 | Deskripsi kosong | TERJAWAB SEBAGIAN — ada dan tidak langka (22364 BRINK, baris ke-2; eksplorasi-data.md §6); proporsinya tidak pernah dihitung — cek mikro 2. |
| U-6 | Duplikat `app_id` / `review_id` | TERJAWAB LEWAT ETL/T10 — `COUNT(*) = COUNT(DISTINCT review_id) = 10.129.675` (AC-06); kohort games↔metadata cocok persis, 0 yatim (test_referential_integrity.py, T10). |
| U-7 | Baris yatim | TERJAWAB LEWAT ETL — `missing_user` 22, `missing_game` 0 pada run penuh (AC-04/AC-06). |
| U-8 | Nilai kosong & ekstrem | TERJAWAB SEBAGIAN — `positive_ratio` 0–100, seluruh 50.872 terisi; `rating` tanpa kosong (9 nilai, jumlah 50.872); harga negatif dan null `helpful`/`funny`/`hours` belum diukur — cek mikro 3. |
| U-9 | Encoding & karakter khusus | TERJAWAB — UTF-8, simbol ™/® tampil sebagai mojibake hanya di konsol PowerShell; ETL membaca UTF-8 eksplisit (eksplorasi-data.md §6). |
| U-10 | Ukuran & jumlah baris vs klaim Kaggle | TERJAWAB — games 50.872 baris / 4.863.790 byte; users 14.306.064 / 193.068.018 byte; total 2.238.703.480 byte ≈ 2,24 GB, cocok dengan klaim; jumlah recommendations tidak dihitung manual, diketahui dari ETL: 41.154.794 baris dibaca. |
| U-11 | Himpunan nilai `rating` | TERJAWAB LENGKAP — tepat 9 nilai + frekuensi, jumlah 50.872 (eksplorasi-data.md §4). |
| U-12 | Rentang & makna `helpful`/`funny`/`hours` | BELUM TERJAWAB — tidak ada statistiknya di bukti mana pun — cek mikro 3. |

**Catatan perbedaan dari PRD:** tidak ada selisih yang ditemukan — header,
format JSON Lines, skala `positive_ratio` 0–100 (dengan konversi ÷100),
9 nilai `rating`, tag `"Indie"` persis, dan deskripsi kosong semuanya
sesuai PRD §2.1–2.2 sebagaimana dikoreksi §2.0.1; pemetaan kolom tidak
berubah (rekonsiliasi Fase 1 di `docs/keputusan-desain.md`).

**Cek mikro penutup (±5 menit, terhadap database yang sudah terisi — tidak
perlu membaca ulang berkas 2,2 GB; nama kolom mengikuti PRD §6 /
`sql/schema.sql`):**
1. U-3/U-8 — di psql: `SELECT COUNT(*) FROM games WHERE release_date IS NULL;` (harapan 0) dan `SELECT MIN(price_usd), MAX(price_usd) FROM games;` (harapan minimum ≥ 0). Bila ada tanggal gagal parse, alasannya tercatat di `notes` entri `etl_logs` tahap games.
2. U-5 — di mongosh: `db.game_metadata.countDocuments({description: ""})` dibagi 50.872 = proporsi deskripsi kosong.
3. U-12/U-8 — di psql: `SELECT COUNT(*) AS total, COUNT(helpful) AS helpful_terisi, COUNT(funny) AS funny_terisi, COUNT(hours_played) AS hours_terisi, MIN(hours_played), MAX(hours_played) FROM recommendations;` Tulis hasilnya ke baris U-12/U-8 di atas, lalu ubah status AC-00 menjadi LULUS.

Catatan: `docs/profiling-dataset.md` sebagai berkas tersendiri tetap tidak
ada; bila penguji menuntut berkas itu persis, salin tabel U-1..U-12 di atas
beserta "Catatan perbedaan dari PRD" ke `docs/profiling-dataset.md` sebagai
catatan gerbang — isinya sudah terverifikasi, hanya wadahnya yang berbeda.

## AC-01 — Infrastruktur 

Langkah: `docker compose up -d`, lalu verifikasi `docker compose ps`,
`\dt` dan `\dv` di psql, serta daftar koleksi/indeks di mongosh.
Hasil: kedua container Up; 5 tabel terbentuk (games, users,
recommendations, live_updates, replay_buffer) beserta view game_stats;
koleksi MongoDB dan indeksnya terbentuk; penerapan ulang skema bersifat
idempotent (pesan NOTICE "already exists, skipping").
Bukti: fase02-psql-tabel-view.png.

## AC-02 — Metadata & Cohort 

Langkah: `--stage metadata --sample` dua kali, verifikasi mongosh,
lalu run penuh oleh manusia.
Hasil: sampel 1.000 dokumen terbaca/termuat dua kali tanpa duplikat;
cohort Indie sampel = 507, cocok dengan hitungan manual
`grep -c '"Indie"'` pada berkas sampel. Run penuh: 50.872 dokumen
termuat, cohort Indie penuh = 27.957 game. Dokumen Monaco (113020)
terverifikasi utuh di mongosh.
Bukti: fase03-kohort-monaco.png.

## AC-03 — Games Hanya Cohort 

Langkah: `--stage games --sample` dua kali; query pemeriksaan Monaco
dan Prince of Persia; run penuh oleh manusia; query rentang
positive_ratio.
Hasil: sampel 1.000 terbaca, 507 termuat, 493 dibuang seluruhnya
beralasan not_in_cohort, idempotent. Monaco (113020) ada di games
(positive_ratio 0,9200; total_reviews 3.722; price_usd 14,99);
Prince of Persia (13500, non-Indie) tidak ada. Rentang positive_ratio
sampel 0,1000–1,0000 (skala sumber 0–100 dibagi 100). Run penuh:
games = 27.957, persis sama dengan cohort MongoDB — nol app_id yatim
di kedua arah (diperkuat test_referential_integrity.py pada T10);
rentang 0–1 seluruh tabel divalidasi test_data_consistency.py.
Bukti: fase04-games-users-sampel.png.

## AC-04 — Recommendations Penuh 

Langkah: run penuh `--stage recommendations` oleh manusia (412 chunk);
bandingkan ringkasan run dengan etl_logs.
Hasil: rows_read 41.154.794 = rows_loaded 10.129.675 +
rows_discarded 31.025.119 (not_in_cohort 31.025.097 + missing_user 22;
missing_game 0). Identitas cocok persis dengan etl_logs; selesai
dalam 1.548 detik tanpa kehabisan memori. Pencocokan manual satu
baris (review_id 1511) cocok 100% dengan sumber.
Catatan dataset: recommendations.csv tidak terurut selaras dengan
games.csv (baris cohort pertama di baris data 1.512) dan sebagian
judul indie terkenal bertag kosong di sumber sehingga berada di luar
definisi cohort D-1 — temuan data, bukan kesalahan ETL
(didokumentasikan di catatan-teknis.md).

## AC-05 — `--stage full` Dua Kali 

Belum dijalankan. Rencana: jalankan `python -m etl.run_etl
--stage full` dua kali, catat jumlah semua tabel/koleksi sesudah
masing-masing run. Yang harus identik: games 27.957; users
14.306.063; recommendations 10.129.675; game_metadata 50.872;
game_media 200; hidden gem 7.337. Satu-satunya pengecualian yang
diizinkan ETL-09: etl_logs bertambah setiap run. Sisi sampel AC ini
sudah didukung test_idempotency.py (T10, lulus).

## AC-06 — Interupsi & Run Ulang 

Langkah: `--stage recommendations` dihentikan paksa (Ctrl+C)
sesudah chunk 10, lalu perintah yang sama dijalankan ulang
hingga selesai; verifikasi COUNT(*) vs COUNT(DISTINCT review_id).
Hasil: run ulang selesai 412 chunk dengan rows_read 41.154.794,
rows_loaded 10.129.675, rows_discarded 31.025.119 (termasuk 22
missing_user yang sama), newly_inserted = 0, elapsed 731,74 detik.
COUNT(*) = COUNT(DISTINCT review_id) = 10.129.675 — tidak ada
duplikat maupun baris hilang/rusak akibat interupsi (satu chunk
satu transaksi; chunk yang terinterupsi ter-rollback utuh).
Bukti: fase10-ac06-interupsi.png, fase10-ac06-selesai.png,
fase10-ac06-verifikasi.png.

## AC-07 — Validasi Hidden Gem D-3 

Acuan: median total_reviews cohort (D-2) = 46; hidden gem (D-3) =
positive_ratio >= 0,80 DAN total_reviews < 46.

| Pemeriksaan agregat | Hasil |
|---|---|
| Total game cohort | 27.957 |
| Hidden gem | 7.337 |
| Bukan hidden gem | 20.620 |
| MIN positive_ratio hidden gem | 0,8000 |
| MAX total_reviews hidden gem | 45 (< 46) |
| False negative (memenuhi D-3 tapi bukan gem) | 0 |

Lima sampel teratas (semua positive_ratio 1,0000, total_reviews 45):
490100 Quell Zen; 587310 Soma Spirits: Rebalance; 676130 Without
Within 3; 797570 Go Morse Go! Arcade Edition; 1511140 Laser
Attraction — kelima baris diperiksa satu per satu di game_stats dan
memenuhi D-3. Diperkuat test_hidden_gem_logic.py (T10): tidak ada
false positive maupun false negative di seluruh tabel.
Keputusan terkait: game_stats dikonversi menjadi MATERIALIZED VIEW
karena EXPLAIN ANALYZE view biasa melampaui 1 detik pada data penuh
(aturan PRD §6.1); sesudah konversi kueri dasbor < 10 ms dengan
jumlah identik (dicatat di keputusan-desain.md).
Bukti: fase06-validasi-hidden-gem.png.

## AC-08 — Enrichment Foto 

Langkah: `--stage enrichment --limit 10` dua kali (idempotensi),
lalu run penuh 200 game oleh manusia; periksa game_media di mongosh.
Hasil: run penuh 200/200 dokumen berstatus ok via CDN (0 appdetails,
0 missing), game_media = 200 dokumen — memenuhi rentang 100–200.
Daftar D-4 stabil: 5 app_id pertama sama persis dengan 5 sampel
AC-07. Catatan jujur: cabang appdetails dan missing tidak pernah
terpicu oleh data asli (seluruh 200 game memiliki gambar CDN);
kedua cabang dibuktikan lewat uji mock test_enrichment_fallback.py
pada T10 (lulus).
Bukti: fase07-enrichment-sampel.png, fase07-enrichment-penuh.png.

## AC-09 — Live Polling 

Langkah: `--stage polling --limit 10`; cocokkan satu game manual
antara respons appdetails, tabel live_updates, games, dan
game_stats; periksa panel Live Updates di dasbor.
Hasil: live_updates bertambah 0 → 10 baris, etl_logs mencatat run
polling, games.price_usd dan updated_at terbarui tanpa mengubah
total_reviews. Pencocokan manual Quell Zen: harga appdetails 699
sen → 6,99 identik di live_updates, games, dan game_stats sesudah
REFRESH. Perubahan harga nyata tertangkap (676130: 1,24 → 4,99;
497690: 14,99 → 7,49). Panel Live Updates menampilkan observasi
dan waktu sinkron terakhir. Catatan: appdetails mengembalikan
recommendations: null untuk seluruh game uji sehingga
steam_recommendations kosong dan hanya harga yang terlacak
(keterbatasan API, dicatat di catatan-teknis.md); putaran penuh
200 game belum dijalankan sehingga panel masih berisi 32 observasi
dari 10 game — kriteria satu run polling terpenuhi, putaran penuh
bersifat penyempurnaan tampilan.
Bukti: fase07-polling-limit10.png.

## AC-10 — Replay Demo 

Uji mekanisme oleh (tabel asli, --fraction 0.0001):
prepare memindahkan 1.013 baris terbaru ke replay_buffer
(10.129.675 → 10.128.662); prepare kedua ditolak selama buffer
belum kosong; 5 batch × 250 mengembalikan seluruhnya hingga
10.129.675, buffer 0, matches_original=true di etl_logs; batch
pada buffer kosong selesai tanpa error; baris contoh review_id
37449768 terverifikasi identik sesudah kembali.
Run skala demo oleh manusia dengan dasbor terbuka (26 Nov 2026):
--prepare --fraction 0.05 memindahkan 506.484 baris
(→ 9.623.191; 25,17 detik); --batch 100000 --interval 5 sebanyak
6 putaran mengembalikan seluruhnya (final 10.129.675, buffer 0;
135,66 detik). Setiap prepare/batch diakhiri REFRESH MATERIALIZED
VIEW CONCURRENTLY game_stats sehingga perubahan tercermin di
dasbor pada auto-refresh berikutnya.
Bukti: fase08-replay-siklus.png.

## AC-11 — Mode Temukan Game Untukmu 

Hasil: fungsi skor murni diverifikasi manual pada Monaco (113020):
dengan tag [Stealth, Co-op, Heist] skor kode 77,6 = hitungan manual
100 × (0,50×3/3 + 0,30×0,92 + 0,20×0); tanpa tag skor 27,6 dan
alasan tidak mengklaim kecocokan tag (REC-05). Kartu Quell Zen di
dasbor menampilkan skor 50,0 (0,30×1,00 + 0,20 bonus hidden gem)
dengan harga live $6,99. Hasil maksimal 20 kartu terurut skor;
kombinasi mustahil (tag Rugby + harga maks $0,01) menghasilkan
pesan ramah REC-06, terbukti lewat AppTest (0 exception) dan
test_recommendation_scoring.py.
Bukti: fase09-rekomendasi.png, fase09-kasus-kosong.png.

## AC-12 — Panel Dasbor & Isolasi Error 

Sisi sumber data: seluruh panel menampilkan data dari sumber §8.3
— diverifikasi per fungsi kueri (KPI cocok dengan angka
resmi; total tren bulanan tepat 10.129.675; Top 10 dipimpin
Unturned) dan terlihat langsung pada kunjungan manusia 26 Nov
2026 (header status ETL, kartu rekomendasi berfoto, scatter
saturasi tag dan harga vs ratio dengan zona hidden gem, daftar
hidden gem terpaginasi 7.337/367 halaman, log ETL per tahap,
panel Live Updates).
Sisi DB-05: perilaku isolasi error teramati langsung saat kedua
database mati (26 Nov 2026) — dasbor tidak crash, header dan
indikator auto-refresh tetap hidup, setiap panel menampilkan
pesan error yang jelas pada tempatnya. Uji formal satu DB
(docker compose stop mongo saja, PostgreSQL tetap hidup) belum
dijalankan; status AC ini menunggu uji ±5 menit tersebut.
Bukti pendukung: fase09-db-mati.png, fase09-panel-analitik.png.

## AC-13 — Backup & Restore 

Langkah: jalankan scripts/backup.ps1, lalu scripts/restore.ps1;
bandingkan seluruh tabel/koleksi database uji vs produksi.
Hasil: artefak postgres_20261126_131542.sql (672.012.073 byte),
folder mongodump, game_metadata.json (19.685.250 byte), dan
game_media.json (62.403 byte) terbentuk. Restore hanya ke
elitis_restore_test dan elitis_mongo_restore_test; perbandingan
cocok 100%: games 27.957, users 14.306.063, recommendations
10.129.675, live_updates 32, replay_buffer 0, game_stats 27.957
(hidden gem 7.337); game_metadata 50.872, raw_metadata 50.872,
game_media 200, etl_logs 34. game_stats tiba sudah terisi dari
dump (pg_dump membawa data materialized view) sehingga REFRESH
tidak diperlukan pada putaran ini; cabang REFRESH tetap tersedia
di skrip sebagai pengaman. Database produksi tidak disentuh.
Pengemasan ZIP penyerahan + uji restore pada lingkungan yang
benar-benar kosong dikerjakan pada Fase 11.
Bukti: fase10-backup-restore.png.

## AC-14 — Tanpa Hardcode & Tanpa Kredensial

Hasil: dasbor tidak memuat angka hardcoded (DB-04) — seluruh
angka berasal dari kueri ke PostgreSQL/MongoDB, terbukti dari
angka dasbor yang berubah mengikuti replay dan harga polling.
Kredensial hanya berada di .env lokal yang ter-gitignore sejak
T0; docker-compose.yml membaca kredensial lewat interpolasi
variabel tanpa nilai tertanam.

## Catatan Rekonsiliasi Users 

Run penuh users (T3): rows_read 14.306.064, rows_loaded
14.306.063, rows_discarded 1 (terlihat pada panel Log ETL
dasbor). Satu baris sumber dibuang saat pemuatan; alasan
spesifiknya tercatat pada notes entri etl_logs run tersebut
dan masih perlu dibaca untuk menutup catatan ini secara resmi.
Selisih ini bukan kehilangan data diam-diam: identitas
read = loaded + discarded berlaku persis.
