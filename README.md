# TPM Meter IoT — prototipe perangkat dan aplikasi

Prototipe perangkat lunak untuk proposal **Penguji Kelayakan Minyak Goreng (TPM Meter Murah)**. Repo ini menyatukan firmware ESP32, API lokal dengan SQLite, aplikasi web responsif, simulator data, serta opsi notifikasi Telegram. Aplikasi webnya dirancang bisa ditambahkan ke layar utama HP sebagai PWA; ini bukan file APK atau aplikasi yang sudah diterbitkan di toko aplikasi.

> **Status riset:** aplikasi dan jalur data dapat dicoba secara lokal. Firmware masih memerlukan hardware nyata dan konfigurasi Wi-Fi. Nilai dari simulator bersifat sintetis. Estimasi TPM belum tervalidasi terhadap alat acuan, sehingga prototipe ini bukan alat keamanan pangan dan tidak boleh dipakai sebagai satu-satunya dasar keputusan mengganti minyak.

## Struktur repo

```text
README.md
Dockerfile
.gitignore
service/
  app.py                         API HTTP + SQLite + Telegram opsional
  static/
    index.html                   Aplikasi dashboard responsif
    manifest.webmanifest         Identitas dan pengaturan instalasi PWA
    sw.js                        Service worker untuk aset aplikasi
    icons/
      icon-192.png               Ikon aplikasi 192 × 192
      icon-512.png               Ikon aplikasi 512 × 512
      icon-192-maskable.png      Ikon adaptif 192 × 192
      icon-512-maskable.png      Ikon adaptif 512 × 512
firmware/
  README.md                      Pin, rangkaian dan langkah build ESP32
  platformio.ini                 Konfigurasi PlatformIO
  include/
    secrets.example.h            Contoh konfigurasi tanpa kredensial nyata
    calibration.h                Model default nonaktif sampai kalibrasi
  src/main.cpp                   Akuisisi sensor, skor edge, kirim HTTP
tools/
  simulate_device.py             Generator data sintetis untuk demo
  train_model.py                 Regresi dari data acuan nyata
  calibration_template.csv       Template dataset
  requirements.txt               Dependensi opsional pelatihan
docs/
  iot-architecture.md            Alur IoT, keamanan, dan rencana validasi
tests/
  test_service.py                Tes API, validasi dan penyimpanan
```

## Jalankan demo lokal

Perlu Python 3.10 atau lebih baru. API tidak memerlukan paket Python eksternal.

```bash
cd tpm-meter-iot
python3 service/app.py
```

Buka `http://localhost:8080`. Di terminal lain, kirim seri data sintetis:

```bash
python3 tools/simulate_device.py --count 30 --interval 0.15
```

Data demo ditandai `source=demo`; datanya hanya untuk menguji alur dashboard, bukan hasil eksperimen minyak sungguhan. Untuk mengosongkan riwayat, hentikan server lalu hapus `service/data/readings.db`.

## Buka dan pasang aplikasi di HP

Aplikasi perlu server API yang berjalan dan dapat dijangkau HP. Untuk percobaan di jaringan lokal yang sama, buka `http://ALAMAT-IP-KOMPUTER:8080` di browser HP, dengan mengganti `ALAMAT-IP-KOMPUTER` dengan IP komputer yang menjalankan server. `localhost` di HP menunjuk HP itu sendiri, bukan komputer server. Pastikan firewall dan jaringan mengizinkan akses.

Untuk instalasi PWA dan service worker, gunakan **HTTPS** yang valid; `localhost` adalah pengecualian untuk pengujian di komputer itu sendiri. Alamat HTTP biasa dengan IP LAN umumnya tidak memenuhi syarat instalasi PWA di HP. Repo ini belum menyediakan hosting atau HTTPS siap pakai. Setelah aplikasi tersedia di alamat HTTPS yang bisa diakses HP:

- **Android:** buka aplikasi di Chrome, lalu pilih **Instal aplikasi** atau menu **Tambahkan ke layar utama**, jika pilihan tersebut ditawarkan browser.
- **iPhone:** buka di Safari, tekan **Bagikan** lalu **Tambahkan ke Layar Utama**; ketersediaan dan istilah menu dapat bergantung pada versi iOS.

Tampilan aplikasi bisa disimpan sebagai shell, tetapi pembacaan dan riwayat membutuhkan server yang dapat dijangkau. Data API tidak disimpan sebagai pembacaan offline; ketika koneksi putus, aplikasi harus menunjukkan status tersebut, bukan menganggap data lama sebagai pembacaan terkini.

**Keamanan:** server default mendengarkan pada semua antarmuka jaringan (`0.0.0.0`). `DEVICE_TOKEN` melindungi pengiriman data POST, tetapi API pembacaan GET belum memiliki autentikasi pengguna. Jangan membuka layanan ke internet dengan hanya mengandalkan token tersebut: tambahkan autentikasi akses-baca, HTTPS, dan pembatasan jaringan sebelum penggunaan di luar jaringan tepercaya. HTTPS tidak otomatis menyembunyikan data dari pengguna yang sudah bisa mengakses endpoint.

## Sambungkan ESP32

1. Salin `firmware/include/secrets.example.h` menjadi `firmware/include/secrets.h`, lalu isi Wi-Fi serta URL API pada jaringan yang sama. File rahasia lokal tersebut diabaikan Git.
2. Ikuti pemetaan pin dan catatan rangkaian di [`firmware/README.md`](firmware/README.md). Sensor kapasitif harus memakai rangkaian pembaca/conditioning yang sesuai; jangan hubungkan probe telanjang langsung ke GPIO atau minyak.
3. Jalankan API di komputer yang dapat dijangkau ESP32. Isi `API_BASE_URL` dengan alamat LAN komputer, misalnya `http://192.168.1.20:8080` (bukan `localhost` dari sisi ESP32).
4. Jika API diakses dari jaringan yang tidak dipercaya, jalankan di balik HTTPS dan tetapkan `DEVICE_TOKEN` di server serta token yang sama di header firmware. Jangan mengekspos HTTP tanpa autentikasi ke internet.
5. Bangun firmware dengan PlatformIO dari folder `firmware/`.

Firmware mengirim data mentah sensor. Sebelum kalibrasi, `tpm_estimate` tetap `null` dan kategori `UNKNOWN`; jangan mengarang angka TPM dari data sensor mentah.

## Kalibrasi model

Isi `tools/calibration_template.csv` dengan sampel berpasangan yang diukur pada suhu tercatat: `capacitance_pf`, `optical_raw`, `temperature_c`, dan nilai TPM dari alat acuan. Nilai acuan harus berasal dari pengukuran nyata yang terdokumentasi.

Setelah tersedia sekurangnya 20 sampel yang mewakili rentang minyak dan suhu, pasang dependensi opsional `python3 -m pip install -r tools/requirements.txt`, lalu jalankan:

```bash
python3 tools/train_model.py --csv tools/my_calibration.csv --out firmware/include/calibration.h
```

Skrip mengeluarkan koefisien regresi dan metrik validasi silang. Jika CSV memuat `batch_id`, validasi silang menahan batch utuh untuk mengurangi kebocoran antarulangan. Koefisien regresi saja tidak cukup untuk mengaktifkan alat: konversi ADC-ke-pF pada firmware juga perlu dikalibrasi terpisah, model perlu ditinjau, dan hasil harus diverifikasi dengan sampel/batch terpisah terhadap alat acuan.

## Opsi IoT

- **Jalur saat ini:** ESP32 → HTTP/JSON → API Python → SQLite → dashboard lokal. Jalur ini membuat demo mudah dijalankan tanpa layanan cloud.
- **Notifikasi:** Telegram opsional ketika kategori berubah ke `RED`. Set `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID` sebagai environment variable di server.
- **Cloud nanti:** deploy API di layanan HTTPS dengan database persisten, lalu ubah `API_BASE_URL`. Untuk banyak perangkat/operasi berkelanjutan, pindahkan ingestion ke broker MQTT dan database time-series; jangan simpan token di source code.

### Notifikasi Telegram opsional

```bash
export TELEGRAM_BOT_TOKEN='token-bot'
export TELEGRAM_CHAT_ID='chat-id'
python3 service/app.py
```

Jika server memakai `DEVICE_TOKEN`, simulator dapat mengirim token dengan opsi `--token`; firmware harus memakai token yang sama.

## Tes

```bash
python3 -m unittest discover -s tests -v
```

## Status pengembangan

- Selesai di repo lokal: API, SQLite, aplikasi web/PWA, simulator, firmware skeleton, template kalibrasi dan tes dasar.
- Belum dilakukan: pembuatan/perakitan alat, pengukuran sampel nyata, validasi terhadap TPM meter, uji lapangan, dan deployment cloud.
- Ambang kategori awal untuk model tervalidasi: `GREEN < 20%`, `YELLOW 20–<24%`, `RED >= 24%`. Ambang final perlu dikonfirmasi dari sumber/standar yang berlaku dan arahan pembimbing.
