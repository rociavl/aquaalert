/******************************************************************************
 * AquaAlert - TDS Calibration Firmware
 * ----------------------------------------------------------------------------
 * Hardware:
 *   - ESP32-WROOM-32 DevKit (30-pin, USB-C)
 *   - DFRobot Gravity Analog TDS Sensor SEN0244 (or equivalent Liccx module)
 *
 * Wiring:
 *   TDS board  "+"  -->  ESP32  3V3
 *   TDS board  "-"  -->  ESP32  GND
 *   TDS board  "A"  -->  ESP32  GPIO 34  (ADC1_CH6, input-only, BLE-safe)
 *
 * Purpose:
 *   Calibration experiment for AquaAlert Bottle conductance sensor.
 *   Reads voltage from TDS module, applies temperature compensation,
 *   prints both raw voltage and uncalibrated TDS (ppm) over Serial in
 *   CSV format ready for Python ingestion.
 *
 * Output format (CSV):
 *   timestamp_ms,voltage_V,voltage_compensated_V,tds_ppm_uncalibrated
 *
 * Author: Rocio (AquaAlert project) - EEBE UPC, Course 295623
 * Adapted from DFRobot reference (Jason, 2017) - GNU LGPL
 *****************************************************************************/

// ---------------- USER CONFIGURATION ----------------------------------------
#define TDS_PIN          34       // GPIO 34 (D34 on board, ADC1_CH6)
#define VREF             3.3f     // ESP32 reference voltage
#define ADC_RESOLUTION   4095.0f  // 12-bit ADC (0..4095)
#define SCOUNT           30       // median filter window
#define SAMPLE_PERIOD_MS 40       // analog read every 40 ms
#define PRINT_PERIOD_MS  1000     // print every 1 s (slower than DFRobot's 800)
#define WATER_TEMP_C     25.0f    // lab water temperature (edit if measured)

// ---------------- INTERNAL STATE --------------------------------------------
int   analogBuffer[SCOUNT];
int   analogBufferTemp[SCOUNT];
int   analogBufferIndex = 0;
float averageVoltage    = 0.0f;
float tdsValue          = 0.0f;
float temperature       = WATER_TEMP_C;

// ---------------- HELPERS ---------------------------------------------------
int getMedianNum(int bArray[], int iFilterLen) {
  int bTab[iFilterLen];
  for (int i = 0; i < iFilterLen; i++) bTab[i] = bArray[i];

  int bTemp;
  for (int j = 0; j < iFilterLen - 1; j++) {
    for (int i = 0; i < iFilterLen - j - 1; i++) {
      if (bTab[i] > bTab[i + 1]) {
        bTemp        = bTab[i];
        bTab[i]      = bTab[i + 1];
        bTab[i + 1]  = bTemp;
      }
    }
  }
  if (iFilterLen & 1) bTemp = bTab[iFilterLen / 2];
  else                bTemp = (bTab[iFilterLen / 2] + bTab[iFilterLen / 2 - 1]) / 2;
  return bTemp;
}

// ---------------- SETUP -----------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(200);

  // ESP32-specific ADC setup
  analogReadResolution(12);                       // 0..4095
  analogSetPinAttenuation(TDS_PIN, ADC_11db);     // full 0..~3.3 V range
  pinMode(TDS_PIN, INPUT);

  // CSV header for Python ingestion
  Serial.println();
  Serial.println(F("# AquaAlert TDS Calibration - ESP32"));
  Serial.print  (F("# Water temperature assumed: "));
  Serial.print  (temperature, 1);
  Serial.println(F(" C"));
  Serial.println(F("timestamp_ms,voltage_V,voltage_compensated_V,tds_ppm_uncalibrated"));
}

// ---------------- LOOP ------------------------------------------------------
void loop() {
  // --- Continuous sampling at SAMPLE_PERIOD_MS ---
  static unsigned long sampleTime = millis();
  if (millis() - sampleTime > SAMPLE_PERIOD_MS) {
    sampleTime = millis();
    analogBuffer[analogBufferIndex++] = analogRead(TDS_PIN);
    if (analogBufferIndex == SCOUNT) analogBufferIndex = 0;
  }

  // --- Periodic CSV print at PRINT_PERIOD_MS ---
  static unsigned long printTime = millis();
  if (millis() - printTime > PRINT_PERIOD_MS) {
    printTime = millis();

    // Copy buffer for median filter
    for (int i = 0; i < SCOUNT; i++) analogBufferTemp[i] = analogBuffer[i];

    // ADC counts -> voltage
    averageVoltage = getMedianNum(analogBufferTemp, SCOUNT)
                     * VREF / ADC_RESOLUTION;

    // Temperature compensation (per DFRobot ref: 2%/C around 25 C)
    float compensationCoefficient = 1.0f + 0.02f * (temperature - 25.0f);
    float compensationVoltage     = averageVoltage / compensationCoefficient;

    // Uncalibrated TDS polynomial (DFRobot factory curve, valid for 0..1000 ppm)
    // NOTE: This was fitted at VCC=5V. With VCC=3.3V it is inaccurate.
    // We log it for reference but base our calibration on voltage_compensated_V.
    tdsValue = (133.42f * compensationVoltage * compensationVoltage * compensationVoltage
               - 255.86f * compensationVoltage * compensationVoltage
               + 857.39f * compensationVoltage) * 0.5f;

    // CSV line: timestamp, raw_V, comp_V, tds_ppm
    Serial.print(millis());            Serial.print(',');
    Serial.print(averageVoltage, 4);   Serial.print(',');
    Serial.print(compensationVoltage, 4); Serial.print(',');
    Serial.println(tdsValue, 1);
  }
}
