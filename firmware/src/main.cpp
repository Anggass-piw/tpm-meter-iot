#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <math.h>
#include "secrets.h"
#include "calibration.h"

#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD ""
#endif
#ifndef API_BASE_URL
#define API_BASE_URL "http://192.168.1.20:8080"
#endif
#ifndef API_TOKEN
#define API_TOKEN ""
#endif
#ifndef DEVICE_ID
#define DEVICE_ID "tpm-esp32-01"
#endif

// Sesuaikan pin dan rangkaian conditioning dengan board yang benar-benar dipakai.
static constexpr int CAP_ADC_PIN = 34;
static constexpr int OPT_ADC_PIN = 35;
static constexpr int ONEWIRE_PIN = 4;
static constexpr uint32_t SEND_INTERVAL_MS = 10000;

OneWire oneWire(ONEWIRE_PIN);
DallasTemperature temperatureSensor(&oneWire);
uint32_t lastSend = 0;

uint16_t readAveragedAdc(int pin) {
  uint32_t sum = 0;
  constexpr int N = 16;
  for (int i = 0; i < N; ++i) {
    sum += analogRead(pin);
    delay(3);
  }
  return static_cast<uint16_t>(sum / N);
}

float readOilTemperatureC() {
  temperatureSensor.requestTemperatures();
  const float value = temperatureSensor.getTempCByIndex(0);
  if (value == DEVICE_DISCONNECTED_C || !isfinite(value)) return NAN;
  return value;
}

String classifyTpm(float tpm) {
  if (tpm >= TPM_RED_MIN) return "RED";
  if (tpm >= TPM_YELLOW_MIN) return "YELLOW";
  return "GREEN";
}

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED || strlen(WIFI_SSID) == 0) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Menghubungkan Wi-Fi");
  const uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 12000) {
    delay(350);
    Serial.print('.');
  }
  Serial.println(WiFi.status() == WL_CONNECTED ? " tersambung" : " gagal; alat tetap offline");
}

void sendReading(uint16_t capRaw, uint16_t optRaw, float tempC) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Offline: pembacaan lokal tersedia, pengiriman dilewati.");
    // TODO: untuk produksi, tambahkan antrean persisten dan kirim ulang setelah online.
    return;
  }

  float capPf = NAN;
  float tpm = NAN;
  String category = "UNKNOWN";
  if (MODEL_READY) {
    capPf = CAP_PF_OFFSET + CAP_PF_PER_ADC * capRaw;
    tpm = MODEL_B0 + MODEL_B_CAP_PF * capPf + MODEL_B_OPTICAL * optRaw + MODEL_B_TEMP * tempC;
    if (tpm < 0) tpm = 0;
    if (tpm > 100) tpm = 100;
    category = classifyTpm(tpm);
  }

  String json = "{\"device_id\":\"" DEVICE_ID "\",\"capacitance_raw\":" + String(capRaw) +
                ",\"optical_raw\":" + String(optRaw) + ",\"temperature_c\":" + String(tempC, 2) +
                ",\"capacitance_pf\":";
  json += isfinite(capPf) ? String(capPf, 4) : "null";
  json += ",\"tpm_estimate\":";
  json += isfinite(tpm) ? String(tpm, 2) : "null";
  json += ",\"category\":\"" + category + "\",\"source\":\"hardware\"}";

  HTTPClient http;
  const String endpoint = String(API_BASE_URL) + "/api/readings";
  if (!http.begin(endpoint)) {
    Serial.println("Gagal memulai koneksi HTTP.");
    return;
  }
  http.addHeader("Content-Type", "application/json");
  if (strlen(API_TOKEN) > 0) http.addHeader("Authorization", String("Bearer ") + API_TOKEN);
  const int code = http.POST(json);
  Serial.printf("POST /api/readings -> %d\n", code);
  if (code < 0) Serial.println(http.errorToString(code));
  http.end();
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  pinMode(CAP_ADC_PIN, INPUT);
  pinMode(OPT_ADC_PIN, INPUT);
  temperatureSensor.begin();
  Serial.println("TPM Meter IoT: model calibrated = " + String(MODEL_READY ? "true" : "false"));
  connectWifi();
}

void loop() {
  connectWifi();
  const uint32_t now = millis();
  if (now - lastSend >= SEND_INTERVAL_MS) {
    lastSend = now;
    const uint16_t capRaw = readAveragedAdc(CAP_ADC_PIN);
    const uint16_t optRaw = readAveragedAdc(OPT_ADC_PIN);
    const float tempC = readOilTemperatureC();
    if (!isfinite(tempC) || tempC < -40 || tempC > 300) {
      Serial.println("Suhu belum terbaca; pengiriman diabaikan.");
    } else {
      Serial.printf("cap=%u opt=%u temp=%.2f C\n", capRaw, optRaw, tempC);
      sendReading(capRaw, optRaw, tempC);
    }
  }
  delay(50);
}
