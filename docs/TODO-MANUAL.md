# Tugas Manual yang Tersisa — ELITIS

Daftar pekerjaan yang memerlukan tindakan manusia dan belum dapat diselesaikan oleh agent.

## Wajib Sebelum Penyerahan

1. **Verifikasi idempotensi `--stage full` penuh (AC-05):**
   Saat ini `etl_logs` baru mencatat 1 kali run `--stage full` penuh. Jalankan sekali lagi:
   ```bash
   python -m etl.run_etl --stage full
   ```
   Pastikan seluruh jumlah tetap identik: `games` **27.957**, `users` **14.306.063**, `recommendations` **10.129.675**, `game_metadata` **50.872**, `game_media` **200**, hidden gem **7.337** (hanya `etl_logs` yang bertambah).

2. **Verifikasi visual dasbor 2 halaman & uji ulang DB-05 (AC-12):**
   Jalankan `streamlit run dashboard/app.py` lalu periksa di browser:
   - Halaman default **Monitoring Pipeline**: urutan panel DB-02, auto-refresh 5 detik via fragment, angka KPI (`27.957`, median `46`, hidden gem `7.337`), daftar hidden gem terpaginasi, Log ETL, Live Updates.
   - Halaman **Temukan Game**: form multiselect tags/harga/platform berfungsi, skor & alasan REC-05 akurat, filter mustahil REC-06 menampilkan pesan ramah, state tersimpan saat berpindah halaman.
   - Matikan MongoDB (`docker compose stop mongo`) untuk memastikan panel PostgreSQL tetap hidup pada tata letak 2 halaman ini, lalu nyalakan lagi (`docker compose start mongo`).

3. **Lengkapi `docs/jurnal-pengerjaan.md`:**
   - Tambahkan entri untuk fase akhir: implementasi `--stage full`, pemisahan dasbor menjadi 2 halaman, finalisasi dokumentasi, dan kegiatan anggota tim lain (selain Gabriel) bila ada.
   - Selaraskan beberapa nama berkas bukti di kolom `Bukti` (mis. `fase02-psql-tabel-view.png`, `fase09-db-mati.png`, dll.) dengan nama berkas aktual di `docs/screenshots/`.

4. **Isi NIM Qori di `README.md`:**
   Ganti placeholder `[Isi NIM]` pada tabel Tim di `README.md` (dan pastikan tautan repositori GitHub sudah sesuai).

5. **Buat backup akhir, ZIP penyerahan, & uji restore lingkungan kosong (AC-13):**
   ```powershell
   .\scripts\backup.ps1
   ```
   - Uji `restore` pada mesin lain atau lingkungan baru setelah `docker compose down -v` dan verifikasi jumlah data kembali utuh.
   - Kemas repositori sesuai aturan penyerahan menjadi berkas ZIP.

## Opsional / Penyempurnaan

- **Polling putaran penuh 200 game (AC-09):** Jalankan `python -m etl.run_etl --stage polling` tanpa `--limit` (±15–25 menit) agar panel Live Updates mencakup lebih banyak observasi dari seluruh 200 game D-4.
- **Berkas `docs/profiling-dataset.md` (AC-00):** Jika penilai mewajibkan nama berkas tersebut secara harfiah, salin tabel U-1..U-12 dari `docs/pengujian.md` ke `docs/profiling-dataset.md`.
