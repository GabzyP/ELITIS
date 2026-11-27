# ELITIS - Engine for Locating Indie Treasures in Steam

> **Menemukan permata tersembunyi di lautan 50.000+ game Steam.**

Steam menyimpan puluhan ribu game indie, namun kebanyakan tenggelam di balik judul-judul populer. Pemain yang ingin menemukan game indie berkualitas yang memiliki rasio ulasan positif tinggi namun belum banyak dikenal harus menyaring katalog secara manual, sebuah proses yang memakan waktu dan sering mengecewakan.

**ELITIS** menjawab masalah itu dengan pipeline data *near real-time* dan dasbor interaktif dua halaman:
- **Temukan Game** — rekomendasi rule-based berdasarkan tag favorit, budget, dan platform. Skor transparan yang bisa dijelaskan.
- **Monitoring Pipeline** — KPI kohort Indie, tren rekomendasi, daftar *hidden gems* terpaginasi, harga live dari Steam Store API, dan log ETL. Semuanya auto-refresh setiap 5 detik.

---

## Arsitektur

ELITIS menggunakan arsitektur **polyglot persistence** (PostgreSQL + MongoDB) yang dihubungkan melalui kunci `app_id` di lapisan aplikasi.

### PostgreSQL
Menyimpan data relasional dan numerik dengan integritas kunci asing (`app_id`, `user_id`) serta indeks analitik:
- **`games`** — 27.957 game kohort Indie (harga, rasio positif, jumlah ulasan).
- **`users`** — 14.306.063 pengguna Steam.
- **`recommendations`** — 10.129.675 ulasan dari pengguna terhadap game kohort.
- **`live_updates`** — observasi harga dan rekomendasi live dari Steam Store API.
- **`replay_buffer`** — penampung sementara untuk demo replay.
- **`game_stats`** — MATERIALIZED VIEW yang menghitung statistik agregat dan menandai *hidden gem* (D-3).

### MongoDB
Menyimpan dokumen semi-terstruktur:
- **`raw_metadata`** — dokumen mentah dari `games_metadata.json` untuk ketertelusuran.
- **`game_metadata`** — metadata terstruktur dengan array `tags[]` untuk kohort D-1 dan saturasi tag.
- **`game_media`** — URL gambar hasil enrichment dari CDN Steam (hingga 200 game D-4).
- **`etl_logs`** — log eksekusi setiap tahap pipeline.

---

## Definisi Operasional

| Kode | Nama | Definisi |
|------|------|----------|
| **D-1** | Kohort Indie | Himpunan `app_id` pada `game_metadata` yang elemen `tags`-nya mengandung `"Indie"` secara persis. |
| **D-2** | Median Kohort | Median `total_reviews` atas seluruh baris `games` pada kohort Indie. Saat ini: **46**. |
| **D-3** | Hidden Gem | Game dengan `positive_ratio >= 0,80` **dan** `total_reviews < median_kohort` (D-2). Saat ini: **7.337** game. |
| **D-4** | Game Dilacak | Maksimal 200 game, diprioritaskan dari *hidden gems* (`positive_ratio DESC, total_reviews DESC`), dilengkapi dari `total_recommendations DESC` bila kurang. |
| **D-5** | Near Real-Time | Ingestion per chunk, polling berkala, auto-refresh dasbor tiap 5 detik (`st.fragment`), dan panel Live Updates. |
| **D-6** | Skor Rekomendasi | Lihat rumus REC-03 di bawah. |

### Rumus Skor Rekomendasi (REC-03)

```
skor = 100 × (0,50 × fraksi_tag_cocok + 0,30 × positive_ratio + 0,20 × bonus_hidden_gem)
```

Di mana:
- `fraksi_tag_cocok` = jumlah tag game yang cocok dengan pilihan pengguna / jumlah tag yang dipilih pengguna (0 bila tidak ada tag dipilih).
- `positive_ratio` = rasio ulasan positif game (skala 0–1).
- `bonus_hidden_gem` = 1 jika game adalah *hidden gem* (D-3), 0 jika bukan.

**Contoh:** Monaco (app_id 113020) dengan tag [Stealth, Co-op, Heist], pengguna memilih ketiga tag tersebut, `positive_ratio` = 0,92, bukan hidden gem:
```
skor = 100 × (0,50 × 3/3 + 0,30 × 0,92 + 0,20 × 0) = 100 × (0,50 + 0,276 + 0) = 77,6
```

---

## Cara Menjalankan

### Prasyarat
- **Docker Desktop** (termasuk Docker Compose)
- **Python 3.11+** dengan `pip`
- Dataset Kaggle **[Game Recommendations on Steam](https://www.kaggle.com/datasets/antonkozyriev/game-recommendations-on-steam)** unduh dan letakkan 4 berkasnya di `data/incoming/`

### 1. Siapkan Konfigurasi

```bash
cp .env.example .env
# Edit .env: isi PG_PASSWORD, sesuaikan PG_PORT jika port 5432 sudah dipakai
```

### 2. Instal Dependensi Python

```bash
pip install -r requirements.txt
```

### 3. Jalankan Database

```bash
docker compose up -d
# Tunggu kedua container healthy (postgres dan mongo)
docker compose ps
```

Skema tabel, view, dan indeks terbuat otomatis saat container pertama kali menyala.

### 4. Jalankan Pipeline ETL

**Seluruh tahap inti sekaligus (`metadata` → `games` → `users` → `recommendations`):**
```bash
python -m etl.run_etl --stage full
```

**Atau per tahap (urutan wajib: metadata → games → users → recommendations):**
```bash
python -m etl.run_etl --stage metadata
python -m etl.run_etl --stage games
python -m etl.run_etl --stage users
python -m etl.run_etl --stage recommendations
```

**Tambahkan `--sample` untuk pengujian cepat dengan data sampel:**
```bash
python -m etl.run_etl --stage full --sample
```

### 5. Enrichment Media (Opsional)

```bash
python -m etl.run_etl --stage enrichment           # 200 game D-4
python -m etl.run_etl --stage enrichment --limit 10 # hanya 10 game pertama
```

### 6. Live Polling Harga Steam

```bash
python -m etl.run_etl --stage polling               # seluruh 200 game D-4
python -m etl.run_etl --stage polling --limit 10    # hanya 10 game pertama
```

### 7. Scheduler & Folder Watcher (Opsional)

```bash
python -m etl.scheduler    # polling otomatis setiap POLLING_INTERVAL_MINUTES
python -m etl.watcher      # deteksi berkas baru di data/incoming/
```

### 8. Demo Replay

```bash
# Pindahkan 5% recommendations terbaru ke buffer
python -m etl.run_etl --stage replay --prepare --fraction 0.05

# Kembalikan secara bertahap (100.000 baris/batch, jeda 5 detik)
python -m etl.run_etl --stage replay --batch 100000 --interval 5
```

### 9. Jalankan Dasbor Streamlit

```bash
streamlit run dashboard/app.py
```

Buka browser di `http://localhost:8501`. Halaman default: **Monitoring Pipeline**. Navigasi ke **Temukan Game** melalui sidebar.

### 10. Backup & Restore

```powershell
# Backup (PowerShell)
.\scripts\backup.ps1

# Restore ke database uji (PowerShell)
.\scripts\restore.ps1
```

```bash
# Backup (Bash/Linux/Mac)
bash scripts/backup.sh

# Restore
bash scripts/restore.sh
```

Hasil backup tersimpan di folder `backups/` (di-gitignore kecuali `.gitkeep`).

---

## Pengujian Otomatis

```bash
python -m pytest tests/ -v
```

**11 kasus uji** dalam 6 berkas, seluruhnya lulus (`11 passed in 8.46s`):

| Berkas | Kasus Uji | Cakupan |
|--------|--------------------|---------|
| `test_data_consistency.py` | 2 | Jumlah `games` PG = kohort Indie MongoDB; jumlah hidden gem `game_stats` cocok hitung ulang D-3 dan seluruh `positive_ratio` berada di `0..1` |
| `test_referential_integrity.py` | 2 | 0 rekomendasi yatim (`user_id`/`app_id`); 0 selisih `app_id` antara `games` PG dan kohort MongoDB |
| `test_hidden_gem_logic.py` | 2 | 5 sampel AC-07 memenuhi D-3 di `game_stats`; 0 *false positive* & 0 *false negative* pada batas D-3 |
| `test_idempotency.py` | 1 | Tahap `metadata`, `games`, `users` dijalankan dua kali pada sampel (DB terisolasi) → jumlah identik |
| `test_recommendation_scoring.py` | 2 | Skor Monaco (77,6 / 27,6) & alasan REC-05 tanpa klaim palsu; filter mustahil REC-06 mengembalikan daftar kosong |
| `test_enrichment_fallback.py` | 2 | Fallback CDN gagal → `appdetails`, serta CDN & `appdetails` gagal → `missing` via mock HTTP |

---

## Struktur Repositori

```text
ELITIS/
├── docker-compose.yml          # Layanan PostgreSQL & MongoDB
├── .env.example                # Template variabel lingkungan
├── requirements.txt            # Dependensi Python
├── README.md
├── .gitignore
│
├── data/
│   ├── incoming/               # Dataset Kaggle (di-gitignore)
│   └── samples/                # Sampel data untuk --sample
│
├── etl/
│   ├── config.py               # Konfigurasi & koneksi database
│   ├── extract.py              # Pembacaan flat file (utuh & per chunk)
│   ├── transform.py            # Pembersihan, pemetaan tipe, filter kohort
│   ├── load.py                 # Upsert idempotent ke PostgreSQL & MongoDB
│   ├── enrichment.py           # Enrichment media dari CDN Steam
│   ├── live_polling.py         # Polling harga live Steam Store API
│   ├── replay.py               # Mode replay untuk simulasi aliran data
│   ├── scheduler.py            # Penjadwalan polling berkala (APScheduler)
│   ├── watcher.py              # Pemantau folder data/incoming (watchdog)
│   └── run_etl.py              # CLI orkestrasi pipeline ETL
│
├── dashboard/
│   ├── app.py                  # Entry point Streamlit
│   ├── shared.py               # Modul bersama: query, skor, filter
│   ├── favicon.ico             # Ikon browser
│   └── app_pages/
│       ├── monitoring.py       # Halaman Monitoring Pipeline
│       └── temukan_game.py     # Halaman Temukan Game
│
├── sql/
│   └── schema.sql              # Skema tabel, indeks, MATERIALIZED VIEW
│
├── mongo/
│   └── indexes.js              # Definisi indeks koleksi MongoDB
│
├── scripts/
│   ├── backup.ps1              # Backup database (PowerShell)
│   ├── backup.sh               # Backup database (Bash)
│   ├── restore.ps1             # Restore database (PowerShell)
│   └── restore.sh              # Restore database (Bash)
│
├── tests/
│   ├── test_data_consistency.py
│   ├── test_enrichment_fallback.py
│   ├── test_hidden_gem_logic.py
│   ├── test_idempotency.py
│   ├── test_recommendation_scoring.py
│   └── test_referential_integrity.py
│
├── docs/
│   ├── keputusan-desain.md     # Keputusan arsitektur & teknis
│   ├── catatan-teknis.md       # Kendala teknis & solusi
│   ├── pengujian.md            # Laporan verifikasi AC-00..AC-14
│   ├── jurnal-pengerjaan.md    # Jurnal kegiatan per fase
│   ├── eksplorasi-data.md      # Hasil eksplorasi dataset Fase 1
│   ├── TODO-MANUAL.md          # Tugas manual yang tersisa
│   └── screenshots/            # Bukti tangkapan layar
│
└── backups/                    # Hasil backup lokal (di-gitignore)
```

---

## Kelompok 5

| Nama | NIM |
|------|-----|
| Gabriel Glenn Peter Pardede | 241712041 |
| Ferlita Kristiani Hulu | 241712025 |
| Adriel Gerald Lumbantobing | 241712029 |
| Auzan Taris | 241712015 |
| Qori | 231712 |

**Repositori:** [https://github.com/GabzyP/ELITIS](https://github.com/GabzyP/ELITIS)
