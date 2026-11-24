# Keputusan Desain Teknis — ELITIS

Catatan ringkas keputusan teknis yang diambil selama pengerjaan proyek.

## T0 — Kerangka Repositori
- **`APScheduler>=3.10.4,<4.0.0` di `requirements.txt`:** Membatasi ke seri 3.x agar kompatibel dengan API stabil (`BlockingScheduler`/`BackgroundScheduler`) dan tidak terkena perubahan besar di versi 4.x.
- **`.gitignore`:** Menambahkan aturan standar Python (`__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.venv/`), hasil dump backup (`backups/*.sql`, `backups/*.zip`, `backups/mongo/`), serta mempertahankan aturan awal untuk `data/incoming/`, `.env`, dan dokumen instruksi lokal.
- **Skrip `scripts/backup.ps1` & `scripts/restore.ps1`:** Dipilih ekstensi `.ps1` mengikuti lingkungan kerja Windows (PowerShell); implementasi penuh dikerjakan pada T10.
