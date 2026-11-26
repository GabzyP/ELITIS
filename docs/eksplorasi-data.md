# Eksplorasi Data ELITIS

- **Sumber data:** Dataset Kaggle "Game Recommendations on Steam" (Anton Kozyriev), berkas lokal di `data/incoming/`
- **Metode:** pemeriksaan lewat terminal (PowerShell `Get-Content`/`Get-ChildItem`/`Import-Csv`, cmd `find`), tanpa mengubah berkas asli.

Dokumen ini adalah hasil pemeriksaan Fase 1. Semua angka di bawah ini berasal dari berkas yang benar-benar diunduh, bukan dari halaman Kaggle.

## 1. Ukuran berkas dan jumlah baris

| Berkas | Ukuran (byte) | Ukuran (±) | Baris data |
|---|---|---|---|
| `games.csv` | 4.863.790 | 4,86 MB | 50.872 |
| `users.csv` | 193.068.018 | 193,07 MB | 14.306.064 |
| `games_metadata.json` | 17.548.605 | 17,55 MB | (lihat catatan) |
| `recommendations.csv` | 2.023.223.067 | 2,02 GB | (lihat catatan) |
| **Total** | **2.238.703.480** | **±2,24 GB** | |

Catatan metode:

- Jumlah baris dihitung dengan `find /c /v ""` (cmd) lalu dikurangi 1 baris header. Metode ini menghitung baris fisik; angka pasti akan dikonfirmasi oleh log ETL saat data dimuat.
- Jumlah baris `recommendations.csv` tidak dihitung manual karena tidak diwajibkan PANDUAN dan berkasnya sangat besar (klaim Kaggle: 41 juta+ baris); angka pastinya akan diketahui dari log ETL per chunk.
- Jumlah dokumen `games_metadata.json` belum dihitung; karena formatnya JSON Lines (lihat §3), satu baris = satu dokumen.
- Total ukuran ±2,24 GB cocok dengan klaim halaman Kaggle.

## 2. Pemeriksaan header 

| Berkas | Header asli | Status |
|---|---|---|
| `games.csv` | `app_id, title, date_release, win, mac, linux, rating, positive_ratio, user_reviews, price_final, price_original, discount, steam_deck` | Sesuai |
| `users.csv` | `user_id, products, reviews` | Sesuai |
| `recommendations.csv` | `app_id, helpful, funny, date, is_recommended, hours, user_id, review_id` | Sesuai |
| `games_metadata.json` | Kunci per dokumen: `app_id, description, tags` | Sesuai |

Tidak ditemukan selisih nama kolom maupun urutan pada keempat berkas.

Format nilai pada baris-baris awal juga sesuai asumsi :

- Nilai boolean ditulis huruf kecil `true`/`false` (kolom `win/mac/linux` dan `is_recommended`).
- Tanggal berformat ISO `YYYY-MM-DD` (contoh: `2008-11-21`, `2022-12-12`).

## 3. Format persis `games_metadata.json`

**Format: JSON Lines** — satu dokumen JSON lengkap per baris, berkas tidak diawali `[` dan bukan array JSON. Parser ETL harus membaca berkas per baris.

Setiap dokumen memiliki tepat tiga kunci: `app_id` (angka), `description` (teks, boleh kosong), `tags` (array string).

Tiga contoh dokumen pertama:

```json
{"app_id":13500,"description":"Enter the dark underworld of Prince of Persia Warrior Within, the sword-slashing sequel to the critically acclaimed Prince of Persia: The Sands of Time™. Hunted by Dahaka, an immortal incarnation of Fate seeking divine retribution, the Prince embarks upon a path of both carnage and mystery to defy his preordained death.","tags":["Action","Adventure","Parkour","Third Person","Great Soundtrack","Singleplayer","Platformer","Time Travel","Atmospheric","Classic","Hack and Slash","Time Manipulation","Gore","Fantasy","Story Rich","Dark","Open World","Controller","Dark Fantasy","Puzzle"]}
{"app_id":22364,"description":"","tags":["Action"]}
{"app_id":113020,"description":"Monaco: What's Yours Is Mine is a single player or co-op heist game. Assemble a crack team of thieves, case the joint, and pull off the perfect heist.","tags":["Co-op","Stealth","Indie","Heist","Local Co-Op","Strategy","Online Co-Op","Top-Down","Action","Multiplayer","Crime","Casual","Great Soundtrack","Adventure","Pixel Graphics","Local Multiplayer","Controller","2D","Singleplayer","Loot"]}
```

## 4. Nilai `rating` pada `games.csv`

Ditemukan tepat 9 nilai berbeda di seluruh 50.872 baris (dihitung dengan `Import-Csv` + `Group-Object`):

| Rating | Jumlah |
|---|---|
| Positive | 13.502 |
| Very Positive | 13.139 |
| Mixed | 12.157 |
| Mostly Positive | 8.738 |
| Mostly Negative | 1.849 |
| Overwhelmingly Positive | 1.110 |
| Negative | 303 |
| Very Negative | 60 |
| Overwhelmingly Negative | 14 |
| **Total** | **50.872** |

Total hitungan sama persis dengan jumlah baris data, sehingga **tidak ada game dengan `rating` kosong**. Nilai disimpan apa adanya sebagai `rating_category` (teks) sesuai, tidak ada perubahan skema yang diperlukan.

## 5. Rentang `positive_ratio`

- Minimum: **0**
- Maksimum: **100**
- Terhitung pada: **50.872** nilai (semua baris memiliki nilai, tidak ada yang kosong)

Ini mengonfirmasi skala sumber 0–100 sesuai, sehingga ETL tetap membagi nilai ini dengan 100 menjadi skala 0–1 sebelum dibandingkan dengan ambang hidden gem 0,80.

## 6. Kekhususan lain yang ditemukan

1. **Deskripsi kosong benar-benar ada.** Dokumen `app_id` 22364 (BRINK) memiliki `"description":""` — sudah ditemukan pada baris ke-2 berkas metadata, jadi kasus ini tidak langka. Dashboard harus siap menampilkan game tanpa deskripsi.
2. **Tag ditulis persis `"Indie"`.** Contoh: dokumen `app_id` 113020 (Monaco) memuat `"Indie"` pada array `tags`-nya (I kapital, sisanya huruf kecil). Bentuk ini persis yang dicari filter kohort D-1.
3. **Tidak semua dokumen ber-tag Indie.** Dua dokumen pertama (13500 dan 22364) tidak memuat tag `"Indie"`; berkas metadata berisi seluruh game Steam dan kohort Indie memang harus disaring.
4. **Encoding UTF-8 bersimbol khusus.** Judul dan deskripsi mengandung simbol seperti ™ dan ®. Terminal PowerShell menampilkannya sebagai `â„¢` (kesalahan tampilan konsol, bukan berkasnya), sedangkan isi berkas terbaca benar di editor. ETL wajib membaca berkas dengan encoding UTF-8 secara eksplisit.

## 7. Kesimpulan untuk tahap berikutnya

- Tidak ditemukan selisih terhadap PRD §2 pada header, format metadata, skala `positive_ratio`, maupun bentuk tag `"Indie"`. Rencana pemetaan kolom PRD dapat dipakai apa adanya.
- Parser metadata membaca JSON Lines per baris; semua berkas dibaca sebagai UTF-8.
- Hal yang belum diverifikasi pada fase ini dan akan terlihat dari log/profiling ETL: duplikat `app_id`, baris yatim (orphan) antarberkas, dan jumlah baris pasti `recommendations.csv`.
