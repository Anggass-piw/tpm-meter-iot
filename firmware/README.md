# Firmware ESP32

Sketch ini membaca 2 kanal ADC (probe kapasitif melalui rangkaian conditioning dan sensor optik), temperatur DS18B20, lalu mengirim data lewat HTTP POST ke API lokal. Nilai dibaca 16 kali dan dirata-ratakan.

## Pin default

| Fungsi | GPIO ESP32 |
|---|---:|
| Keluaran rangkaian sensor kapasitif (ADC) | 34 |
| Keluaran fotodioda / modul optik (ADC) | 35 |
| Data DS18B20 | 4 |
| Catu DS18B20 | 3V3 dan GND, resistor pull-up 4.7 kΩ pada jalur data |

Pemetaan ini hanya titik awal. Pastikan sinyal tidak melebihi batas 3.3 V ESP32 dan cocokkan pin dengan board yang digunakan.

## Sensor kapasitif perlu rangkaian pembaca

GPIO ESP32 tidak mengukur kapasitansi secara langsung. Probe pelat harus disambungkan ke rangkaian pengubah kapasitansi-ke-tegangan/ke-frekuensi atau CDC yang aman, lalu keluaran analog 0–3.3 V masuk ke GPIO 34. Koefisien untuk mengubah ADC menjadi pF masih placeholder di `include/calibration.h`; jangan anggap nilainya sebagai pengukuran pF. Rancang probe berisolasi dan gunakan minyak yang sudah didinginkan ke rentang uji aman. Hindari kontak listrik terbuka dengan minyak atau wadah logam.

## Build

```bash
cp include/secrets.example.h include/secrets.h
# edit secrets.h: SSID, password, URL API, token bila dipakai
pio run
pio device monitor
```

`secrets.h` tidak dilacak Git. Jangan menempelkan kata sandi Wi-Fi atau token ke issue, README, atau serial log.

## Model dan status

Secara default `MODEL_READY=false`: firmware mengirim sensor mentah, `tpm_estimate=null`, dan `category=UNKNOWN`. Setelah data nyata dikumpulkan terhadap meter TPM acuan, skrip `tools/train_model.py` dapat menghasilkan koefisien regresi. Tinjau model serta prosedur validasinya sebelum menyalin koefisien ke header dan mengaktifkan flag. Ambang 20/24% merupakan nilai awal proposal, bukan klaim sertifikasi.

## Ketahanan koneksi

Firmware tetap dapat membaca sensor saat Wi-Fi terputus, tetapi versi ini belum menyimpan antrean offline secara persisten; pembacaan ketika offline dilewati. Untuk uji lapangan, implementasikan antrean NVS/flash, retry dengan backoff, timestamp RTC/NTP, dan acknowledgement deduplikasi sebelum mengandalkan kehilangan data nol.
