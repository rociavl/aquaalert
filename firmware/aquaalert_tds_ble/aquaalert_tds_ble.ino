/******************************************************************************
 * AquaAlert - TDS BLE Live Stream
 * ----------------------------------------------------------------------------
 * Hardware:
 *   - ESP32-WROOM-32 DevKit (30-pin, USB-C)
 *   - DFRobot Gravity Analog TDS Sensor SEN0244 (or equivalent Liccx module)
 *
 * Wiring (same as the calibration firmware):
 *   TDS  "+"  -->  ESP32  3V3
 *   TDS  "-"  -->  ESP32  GND
 *   TDS  "A"  -->  ESP32  GPIO 34  (ADC1_CH6, input-only, BLE-safe)
 *
 * Purpose:
 *   Streams the *calibrated* salivary TDS (ppm) over Bluetooth Low Energy so a
 *   web page (or any BLE client) can plot it in real time. Uses the Nordic
 *   UART Service (NUS), which Web Bluetooth supports out of the box.
 *
 *   Calibration line (from calibrate.py over the 57-850 ppm linear range):
 *      V = 0.0025 * c - 0.059      (in volts, c in ppm)
 *   The intercept is replaced by an auto-tare at boot: the firmware holds
 *   for 5 s with the sensor in clean (deionised) water, measures V_blank,
 *   and from then on uses the slope-only formula
 *      c = (V_compensated - V_blank) / 0.0025
 *   so a reading of 0 ppm really gives 0 (the cero is physically measured,
 *   not extrapolated). To re-tare, just reset the ESP32 with the sensor in
 *   clean water.
 *
 * BLE protocol:
 *   - Device name:        AquaAlertBottle
 *   - Service:            6E400001-B5A3-F393-E0A9-E50E24DCCA9E   (NUS)
 *   - TX characteristic:  6E400003-B5A3-F393-E0A9-E50E24DCCA9E   (notify)
 *
 *   Each notification is an ASCII number followed by '\n', e.g. "412.7\n".
 *
 * Author: Rocio (AquaAlert project) - EEBE UPC, Course 295623
 *****************************************************************************/

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// ---------------- USER CONFIGURATION ----------------------------------------
#define TDS_PIN          34       // GPIO 34 (ADC1_CH6, input-only, BLE-safe)
#define VREF             3.3f
#define ADC_RESOLUTION   4095.0f
#define SCOUNT           30
#define SAMPLE_PERIOD_MS 40
#define NOTIFY_PERIOD_MS 1000     // send one ppm reading per second
#define WATER_TEMP_C     25.0f
#define LED_PIN          2        // built-in LED on most ESP32 DevKits

// Slope-only calibration (intercept replaced by auto-tare at boot)
#define CAL_M            0.0025f  // V per ppm, from NaCl calibration

// Auto-tare on boot
#define TARE_DURATION_MS 5000     // sample the blank for 5 s after reset
#define TARE_PERIOD_MS   100      // one ADC read every 100 ms (~50 samples)

// Nordic UART Service UUIDs
#define NUS_SERVICE      "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define NUS_TX_CHAR      "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

// ---------------- INTERNAL STATE --------------------------------------------
int   analogBuffer[SCOUNT];
int   analogBufferTemp[SCOUNT];
int   analogBufferIndex = 0;
float temperature       = WATER_TEMP_C;
float V_blank           = 0.0f;   // set by autoTare() at boot

BLECharacteristic* txChar = nullptr;
bool clientConnected = false;

// ---------------- BLE callbacks ---------------------------------------------
class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* s)    override { clientConnected = true;  }
  void onDisconnect(BLEServer* s) override {
    clientConnected = false;
    BLEDevice::startAdvertising();   // resume advertising after a disconnect
  }
};

// ---------------- HELPERS ---------------------------------------------------
int getMedianNum(int bArray[], int iFilterLen) {
  int bTab[iFilterLen];
  for (int i = 0; i < iFilterLen; i++) bTab[i] = bArray[i];
  int bTemp;
  for (int j = 0; j < iFilterLen - 1; j++) {
    for (int i = 0; i < iFilterLen - j - 1; i++) {
      if (bTab[i] > bTab[i + 1]) {
        bTemp       = bTab[i];
        bTab[i]     = bTab[i + 1];
        bTab[i + 1] = bTemp;
      }
    }
  }
  if (iFilterLen & 1) bTemp = bTab[iFilterLen / 2];
  else                bTemp = (bTab[iFilterLen / 2] + bTab[iFilterLen / 2 - 1]) / 2;
  return bTemp;
}

// ---------------- AUTO-TARE -------------------------------------------------
// Hold the sensor in clean water for TARE_DURATION_MS after reset; the LED
// blinks the whole time. Captures the sensor's actual zero so 0 ppm reads 0.
void autoTare() {
  Serial.println(F("# Taring (5 s) — keep the sensor in clean water..."));
  const int N = TARE_DURATION_MS / TARE_PERIOD_MS;
  int samples[N];
  for (int i = 0; i < N; i++) {
    samples[i] = analogRead(TDS_PIN);
    digitalWrite(LED_PIN, (i & 1) ? HIGH : LOW);    // blink while taring
    delay(TARE_PERIOD_MS);
  }
  digitalWrite(LED_PIN, LOW);
  int med = getMedianNum(samples, N);               // robust against spikes
  float V_raw = med * VREF / ADC_RESOLUTION;
  float coef  = 1.0f + 0.02f * (temperature - 25.0f);
  V_blank     = V_raw / coef;
  Serial.print(F("# tared at V_blank = "));
  Serial.print(V_blank, 4);
  Serial.println(F(" V"));
}

// ---------------- SETUP -----------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println();
  Serial.println(F("# AquaAlert TDS BLE - ESP32"));

  // ADC
  analogReadResolution(12);
  analogSetPinAttenuation(TDS_PIN, ADC_11db);
  pinMode(TDS_PIN, INPUT);
  pinMode(LED_PIN, OUTPUT);

  // capture the sensor zero *before* BLE so the user knows what's happening
  autoTare();

  // BLE
  BLEDevice::init("AquaAlertBottle");
  BLEServer* server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  BLEService* service = server->createService(NUS_SERVICE);
  txChar = service->createCharacteristic(
      NUS_TX_CHAR, BLECharacteristic::PROPERTY_NOTIFY);
  txChar->addDescriptor(new BLE2902());   // enable notifications
  service->start();

  BLEAdvertising* adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(NUS_SERVICE);
  adv->setScanResponse(true);
  BLEDevice::startAdvertising();

  Serial.println(F("# BLE advertising as 'AquaAlertBottle'"));
  Serial.println(F("timestamp_ms,voltage_compensated_V,ppm_calibrated"));
}

// ---------------- LOOP ------------------------------------------------------
void loop() {
  // continuous sampling
  static unsigned long sampleTime = millis();
  if (millis() - sampleTime > SAMPLE_PERIOD_MS) {
    sampleTime = millis();
    analogBuffer[analogBufferIndex++] = analogRead(TDS_PIN);
    if (analogBufferIndex == SCOUNT) analogBufferIndex = 0;
  }

  // periodic compute + notify
  static unsigned long notifyTime = millis();
  if (millis() - notifyTime > NOTIFY_PERIOD_MS) {
    notifyTime = millis();

    for (int i = 0; i < SCOUNT; i++) analogBufferTemp[i] = analogBuffer[i];

    // counts -> voltage -> compensated voltage
    float V      = getMedianNum(analogBufferTemp, SCOUNT) * VREF / ADC_RESOLUTION;
    float coef   = 1.0f + 0.02f * (temperature - 25.0f);
    float V_comp = V / coef;

    // slope-only calibration with the measured blank:
    //   c = (V_compensated - V_blank) / m   ->  0 ppm reads exactly 0
    float ppm = (V_comp - V_blank) / CAL_M;
    if (ppm < 0.0f) ppm = 0.0f;          // clamp noise dips below the blank

    // serial debug
    Serial.print(millis());      Serial.print(',');
    Serial.print(V_comp, 4);     Serial.print(',');
    Serial.println(ppm, 1);

    // BLE notify (ASCII + '\n', so the web client can parse line-by-line)
    if (clientConnected && txChar) {
      char buf[16];
      int n = snprintf(buf, sizeof(buf), "%.1f\n", ppm);
      txChar->setValue((uint8_t*)buf, n);
      txChar->notify();
    }
  }
}
