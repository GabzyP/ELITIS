"200 dokumen, seluruhnya ok via CDN; 
jalur fallback appdetails dan status missing terimplementasi sesuai ETL 
namun tidak terpicu pada run penuh karena seluruh game D-4 memiliki header CDN"

Run skala demo (dijalankan dengan dasbor terbuka, 2026-11-26):
- --prepare --fraction 0.05: moved_to_buffer 506.484,
  recommendations 10.129.675 -> 9.623.191 (25,17 detik).
- --batch 100000 --interval 5: 6 putaran, seluruh baris
  kembali, recommendations_final 10.129.675,
  replay_buffer 0 (135,66 detik).
- Angka pada grafik tren dan Top 10 di dasbor terlihat
  menurun sesudah prepare dan pulih bertahap tiap batch.