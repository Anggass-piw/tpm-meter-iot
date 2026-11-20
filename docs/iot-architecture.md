# Rancangan IoT TPM Meter

## Alur data yang dibangun

1. Sensor kapasitif, sensor pantulan optik, dan DS18B20 dibaca ESP32. Firmware merata-ratakan 16 sampel ADC.
2. Perhitungan model berjalan di perangkat (edge). Jika belum ada kalibrasi, perangkat mengirim nilai TPM `null` dan kategori `UNKNOWN`—dashboard tetap dapat memperlihatkan telemetri mentah.
3. ESP32 mengirim JSON ke `POST /api/readings` melalui HTTP pada jaringan lokal. Token bearer opsional dapat diaktifkan pada API.
4. API memvalidasi payload, menyimpan rekaman ke SQLite dan menyajikannya ke aplikasi dashboard melalui `GET /api/readings`. Antarmuka web responsif dapat dipasang sebagai PWA pada konteks HTTPS yang sesuai.
5. Jika kategori berpindah menjadi `RED`, server mengirim notifikasi Telegram bila bot token dan chat ID diatur.

## Format pesan

```json
{
  "device_id": "tpm-esp32-01",
  "timestamp": "2026-11-20T02:00:00Z",
  "capacitance_pf": null,
  "capacitance_raw": 1820,
  "optical_raw": 1260,
  "temperature_c": 147.2,
  "tpm_estimate": null,
  "category": "UNKNOWN",
  "source": "hardware"
}
```

## Mengapa HTTP + SQLite untuk versi pertama

Pilihan ini mengurangi jumlah komponen dan memudahkan demonstrasi lokal/skripsi. Untuk beberapa perangkat dan kebutuhan operasi jangka panjang, arsitektur lanjutan yang disarankan adalah MQTT over TLS → broker → worker ingestion → PostgreSQL/TimescaleDB → dashboard. SQLite lokal bukan layanan cloud redundan; siapkan backup, autentikasi, kebijakan retensi, TLS, dan database persisten sebelum pemakaian nyata.

## Keamanan minimum

- Jangan commit `secrets.h`, password Wi-Fi, `DEVICE_TOKEN`, bot token, atau chat ID pribadi.
- Batasi API di LAN; autentikasi bearer untuk ingestion. Token tunggal ini hanya kontrol sederhana, bukan pengganti identitas perangkat/rotasi key. Endpoint pembacaan GET belum memerlukan login; lindungi akses-baca sebelum penggunaan di luar jaringan tepercaya.
- Jangan buka port HTTP langsung ke internet. Jika nanti di-host, gunakan HTTPS, rate limit, validasi perangkat, serta secret manager/environment variables.
- Telegram menerima kategori dan angka estimasi, bukan klaim diagnosis; hindari mengirim data pribadi pedagang.

## Validasi ilmiah sebelum menyebut “TPM meter”

1. Rancang rangkaian kapasitansi-ke-tegangan/frekuensi dan kalibrasikan ADC menjadi pF menggunakan kapasitor standar; verifikasi efek lapisan pelindung.
2. Bakukan geometri, waktu celup, kedalaman, suhu sampel, pengadukan, waktu stabilisasi, dan prosedur pembersihan.
3. Ukur sampel bertingkat dengan alat TPM acuan. Catat pasangan data, batch minyak, pengulangan, dan suhu.
4. Pisahkan data train/test berdasarkan batch, bukan pengukuran berulang dari sampel sama. Hitung RMSE/MAE/R², confusion matrix untuk ambang, bias suhu, repeatability, serta interval ketidakpastian.
5. Uji perangkat dan prosedur lapangan sebelum digunakan untuk keputusan UMKM. Jangan mengklaim kelayakan konsumsi hanya berdasar warna, sensor murah, atau ambang yang belum disahkan.

## Tahap pengembangan lanjut

- Tahap A (tersedia): API lokal, SQLite, dashboard/PWA, simulator, firmware skeleton, template CSV.
- Tahap B: breadboard/rangkaian sensor, pembacaan lokal di OLED dan uji noise; logging offline dengan retry.
- Tahap C: kumpulkan dan audit dataset acuan; validasi regresi dan kategori.
- Tahap D: uji reliabilitas lapangan, enclosure dan keamanan pangan; baru putuskan deployment cloud/MQTT.
