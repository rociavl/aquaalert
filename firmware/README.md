# AquaAlert firmware

Two ESP32 sketches, one per sensor. Both stream CSV over USB serial at
**115200 baud** so the Python tools in [`../analysis`](../analysis) can
capture and plot them.

## `aquaalert_tds_calibration/` — bottle conductance sensor ✅ used

The firmware actually used for the calibration experiment. Drives the
analog TDS / conductivity module (DFRobot SEN0244 / Liccx equivalent) on
an ESP32-WROOM-32 and prints raw + temperature-compensated voltage plus
the (reference-only) ppm value.

| Module pin | ESP32 pin |
|---|---|
| + | 3V3 |
| − | GND |
| A | GPIO34 (ADC1_CH6, input-only) |

**Output:** `timestamp_ms,voltage_V,voltage_compensated_V,tds_ppm_uncalibrated`

> **Why we calibrate on voltage, not ppm:** the DFRobot ppm polynomial was
> fitted at VCC = 5 V. On the ESP32's 3.3 V rail the ppm output is
> inaccurate, so the calibration relates **`voltage_compensated_V`** to the
> known NaCl concentration of each solution instead.

### Calibration run
1. Flash the sketch (Arduino IDE → board "ESP32 Dev Module").
2. For each solution — distilled water, 1 g/100 mL, 2 g/100 mL,
   3 g/100 mL — submerge the probe and capture ~30 s:
   ```bash
   python ../analysis/read_serial.py --label nacl_10gL
   ```
   It prints the mean `voltage_compensated_V` at the end.
3. Put concentration vs mean voltage in `../data/calibration.csv`:
   ```
   concentration_g_L,voltage_compensated_V,note
   0,...,distilled water
   10,...,1 g / 100 mL
   ```
4. Fit and plot the curve:
   ```bash
   python ../analysis/calibrate.py
   ```

## `aquaalert_bia/` — ankle bioimpedance ⚠️ needs bench tuning

Tetrapolar 50 kHz impedance via an AD5941 AFE. Requires the
[AD5940 library](https://github.com/analogdevicesinc/ad5940-examples)
and per-board tuning (excitation amplitude, `RCAL_OHM`, electrode map).
Calibrate against known resistors before trusting absolute values.

| Role | AD5941 pin |
|---|---|
| I+ (inject) | CE0 |
| I− (inject) | SE0 |
| V+ (sense) | AIN1 |
| V− (sense) | AIN0 |

**Output:** `t_ms,freq_hz,z_mag_ohm,z_phase_deg,r_ohm,x_ohm`

> In the prototype the bottle (ESP32 + TDS sensor) is the BLE hub and the
> leg mesh streams to it. For the bench experiments both boards report over
> USB serial directly, which is simpler and produces a CSV for the report.
