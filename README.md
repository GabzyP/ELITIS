# ELITIS — Engine for Locating Indie Treasures in Steam

> **Status:** Kerangka repositori (T0). Dokumentasi operasional lengkap akan diperbarui setelah seluruh tahapan implementasi dan pengujian selesai (T11).

ELITIS adalah dasbor web satu halaman dan pipeline data *near real-time* yang membantu **pemain (gamer)** menemukan game indie berkualitas yang sering tenggelam (*hidden gems*) di katalog Steam.

---

## Arsitektur & Justifikasi Hybrid Database

ELITIS menggunakan arsitektur **polyglot persistence** (PostgreSQL + MongoDB) yang dihubungkan melalui kunci `app_id` di lapisan aplikasi:

1. **MongoDB**
   - Menyimpan dokumen mentah (`raw_metadata`) untuk ketertelusuran.
   - Menyimpan metadata terstruktur (`game_metadata`) dengan array `tags[]` yang fleksibel untuk penentuan cohort Indie (D-1) serta query saturasi tag (`$unwind`).
   - Menyimpan hasil *enrichment* media Steam (`game_media`) dan log eksekusi pipeline (`etl_logs`).
2. **PostgreSQL**
   - Menyimpan data relasional dan numerik (`games`, `users`, `recommendations`, `live_updates`, `replay_buffer`) dengan integritas kunci asing (`app_id`, `user_id`) dan indeks analitik.
   - Menghitung statistik agregasi dan penandaan *hidden gem* secara konsisten lewat view `game_stats`.

---

## Struktur Repositori

```text
elitis/
├── docker-compose.yml      # Layanan PostgreSQL & MongoDB (T1)
├── .env.example            # Template variabel lingkungan (tanpa kredensial asli)
├── requirements.txt        # Dependensi Python
├── README.md               # Dokumentasi proyek
├── .gitignore
├── data/
│   ├── incoming/           # Dataset sumber Kaggle (di-ignore Git)
│   └── samples/            # Sampel data untuk pengujian cepat (--sample)
├── etl/
│   ├── config.py           # Konfigurasi & koneksi database
│   ├── extract.py          # Pembacaan flat file (utuh & per chunk)
│   ├── transform.py        # Pembersihan, pemetaan tipe, filter cohort
│   ├── load.py             # Upsert idempotent ke PostgreSQL & MongoDB
│   ├── enrichment.py       # Enrichment media dari CDN Steam & appdetails
│   ├── live_polling.py     # Polling harga & metadata live Steam Store API
│   ├── replay.py           # Mode replay untuk simulasi aliran data
│   ├── scheduler.py        # Penjadwalan polling berkala (APScheduler)
│   ├── watcher.py          # Pemantau folder data/incoming (watchdog)
│   └── run_etl.py          # CLI orkestrasi pipeline ETL
├── dashboard/
│   └── app.py              # Dasbor Streamlit satu halaman (auto-refresh)
├── sql/
│   └── schema.sql          # Skema tabel, indeks, dan view game_stats
├── mongo/
│   └── indexes.js          # Definisi indeks koleksi MongoDB
├── backups/                # Lokasi hasil backup lokal (di-ignore kecuali README)
├── scripts/                # Skrip backup & restore database
├── tests/                  # Pengujian otomatis (pytest)
└── docs/                   # Keputusan desain, catatan teknis, dan log manual
```

---

## Prasyarat

- Python 3.11+
- Docker & Docker Compose
- Dataset Kaggle **Game Recommendations on Steam** diletakkan di `data/incoming/` (tidak disertakan di repositori).

---

## Cara Menjalankan (Kerangka)

> Langkah rinci beserta opsi lengkap akan dilengkapi setelah implementasi T1–T10 selesai.

1. **Siapkan konfigurasi lingkungan**
   ```bash
   cp .env.example .env
   # Edit .env dan isi kredensial PostgreSQL serta konfigurasi lokal Anda
   ```
2. **Instal dependensi Python**
   ```bash
   pip install -r requirements.txt
   ```
3. **Jalankan database (PostgreSQL & MongoDB)**
   ```bash
   docker compose up -d
   ```
4. **Jalankan pipeline ETL**
   ```bash
   python -m etl.run_etl --stage full
   ```
5. **Jalankan scheduler & folder watcher (opsional / mode otomatis)**
   ```bash
   python -m etl.scheduler
   ```
6. **Jalankan dasbor Streamlit**
   ```bash
   streamlit run dashboard/app.py
   ```

---

## Definisi Operasional & Rumus Rekomendasi

- **D-1 Cohort Indie:** Himpunan `app_id` pada `game_metadata` yang elemen `tags`-nya mengandung `"Indie"` secara persis.
- **D-2 Median Cohort:** Median `total_reviews` atas seluruh baris `games` pada cohort Indie.
- **D-3 Hidden Gem:** Game dengan `positive_ratio >= 0.80` dan `total_reviews < median_cohort` (didefinisikan tunggal di view `game_stats`).
- **D-4 Game yang Dilacak:** Maksimal `TRACKED_LIMIT` (default 200) game yang diprioritaskan dari *hidden gems* (`positive_ratio DESC, total_reviews DESC`), dan bila kurang dari batas dilengkapi dari `total_recommendations DESC`.
- **D-5 Near Real-Time:** Diwujudkan melalui ingestion per chunk, live polling berkala, auto-refresh dasbor tiap 5 detik (`st.fragment`), dan panel Live Updates.
- **D-6 Skor Rekomendasi (REC-03):**
  ```text
  skor = 100 × (0,50 × (tag cocok / tag dipilih) + 0,30 × positive_ratio + 0,20 × (1 jika is_hidden_gem else 0))
  ```
  *(Jika tidak ada tag yang dipilih, komponen tag bernilai `0`.)*

---

## Backup & Restore

Skrip backup dan restore akan disediakan di direktori `scripts/` dengan keluaran di `backups/`. Petunjuk restore terperinci akan ditambahkan pada fase T10–T11.

---

## Tim

- `[Gabriel Glenn Peter Pardede - 241712041]`
- `[Ferlita Kristiani Hulu - 241712025]`
- `[Adriel Gerald Lumbantobing - 241712029]`
- `[Auzan Taris - 241712015]`
- `[Qori]`

Link repositori: `[https://github.com/GabzyP/ELITIS]`
