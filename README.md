# AquaAlert

Early-warning hydration monitoring for older adults during heat waves. Combines a saliva conductance sensor in a smart bottle with a bioelectrical impedance ankle wearable, fused into a single 0–100 hydration index with alerts to user and caregiver.

**Course:** Medical Devices (295623), EEBE — Universitat Politècnica de Catalunya, 2025–2026.

---

## Components

| Device | Sensor | Tech | Target price |
|---|---|---|---|
| **AquaAlert Bottle** | Saliva conductance (Au coplanar electrodes, IDE 100µm, AC) + NTC liquid/ambient temp | ESP32 + BLE 5.0 + Li-Po 500 mAh, IP67 | ~50 € |
| **AquaAlert Leg Mesh** | BIA tetrapolar 50 kHz | AD5941 + BLE to bottle hub | ~30 € |

Both stream data to a multimodal fusion algorithm that outputs the hydration index and triggers tiered alerts.

## Scientific basis

- **HydroSense — Manoj Prabu et al. 2025** *(IJSRSET 12(6):13–18, [doi:10.32628/IJSRSET2513816](https://doi.org/10.32628/IJSRSET2513816))* — **foundational paper.** Saliva pH + TDS on Arduino classifies dehydration. Salivary TDS thresholds: hydrated 200–500, mild 500–700, moderate 700–900, severe ≥900 ppm. AquaAlert's bottle sensor builds on this and adopts its thresholds; the NaCl calibration confirms the sensor is linear across this whole range (saturating only at ~900 ppm, the severe threshold).
- **Lu et al. 2019** *(Scientific Reports)* — gold coplanar electrodes + salivary conductance detect dehydration; sensitivity 86%, specificity 91% vs serum osmolality.
- **PMC 2021** *(N=20, 13 h)* — salivary conductivity rises with water restriction, falls after 1000 mL rehydration. Correlates with urinary osmolality, thirst scale, body weight.
- **Dasgupta 2018** — ankle tetrapolar BIA at 50 kHz validated for total body water (R=0.97 vs gold standard).
- **Ekingen 2022** *(N=242)* — hydration declines with age; 65+ is the primary risk group.

## Repository structure

```
/index.html              ← the user app (mobile-first PWA) — this is the site root
/dashboard.html          ← caregiver console (technical view)
/pitch.html              ← project landing / pitch page (for the presentation)
/live.html               ← live BLE viewer: connects to the ESP32 and plots ppm
/manifest.webmanifest    ← PWA manifest (add-to-home-screen)
/icon.svg, /icon-*.png   ← app icons
/firmware/
  aquaalert_tds_calibration/  ← ESP32 firmware for bottle TDS/conductance (used)
  aquaalert_tds_ble/          ← ESP32 firmware: streams calibrated ppm over BLE (NUS)
  aquaalert_bia/              ← ESP32 firmware for ankle BIA (needs bench tuning)
/analysis/
  read_serial.py         ← serial capture → timestamped CSV
  plot_results.py        ← time-series plot of a capture
  calibrate.py           ← NaCl calibration curve (voltage vs concentration)
  requirements.txt       ← pyserial, pandas, numpy, matplotlib
/data/                   ← experimental CSV results
/docs/                   ← compiled LaTeX reports + generated figures
```

## Demo

The app is the GitHub Pages root — open it on a phone and add it to the home screen:

- **App (user):** https://rociavl.github.io/aquaalert/
- **Caregiver console:** https://rociavl.github.io/aquaalert/dashboard.html
- **Project pitch:** https://rociavl.github.io/aquaalert/pitch.html
- **Live BLE viewer:** https://rociavl.github.io/aquaalert/live.html  *(Chrome/Edge — Web Bluetooth)*

## Market context

3,800+ heat-related deaths per year in Spain. 9 M elderly people. €312 M market in 2024, growing at 14.2 % CAGR through 2033. AquaAlert targets the institutional channel (city councils, care homes, mutuas) — a segment no existing competitor (Nix, hDrop, Epicore, Kenzen) addresses.

## Status

🚧 In development — May 2026.
