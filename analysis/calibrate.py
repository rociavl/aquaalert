#!/usr/bin/env python3
"""Build the NaCl calibration curve from the TDS sensor's compensated voltage.

The DFRobot ppm polynomial was fitted at 5 V, so on the ESP32 (3.3 V) the
ppm value is unreliable. The calibration therefore relates the
temperature-compensated electrode *voltage* to the known NaCl
concentration of each solution.

Reads ../data/calibration.csv with one row per solution:

    concentration_g_L,voltage_compensated_V,note
    0,0.05,distilled water
    10,0.84,1 g / 100 mL
    20,1.42,2 g / 100 mL
    30,1.88,3 g / 100 mL

(get each voltage as the mean printed by read_serial.py for that solution,
or compute it from the per-solution capture with --from-captures)

Fits V = m·c + b, reports R², and saves the plot to ../docs for the report.

Examples
--------
    python calibrate.py
    python calibrate.py --csv ../data/calibration.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
except ImportError:
    sys.exit("Missing deps. Run:  pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "data" / "calibration.csv"
SIGNAL = "voltage_compensated_V"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "calibration_curve.png")
    args = ap.parse_args()

    if not args.csv.exists():
        sys.exit(f"{args.csv} not found.\n"
                 f"Create it with columns: concentration_g_L,{SIGNAL},note")

    df = pd.read_csv(args.csv).sort_values("concentration_g_L")
    if SIGNAL not in df.columns:
        sys.exit(f"Column '{SIGNAL}' missing from {args.csv.name}. "
                 f"Found: {list(df.columns)}")

    c = df["concentration_g_L"].to_numpy(float)
    v = df[SIGNAL].to_numpy(float)
    if len(c) < 2:
        sys.exit("Need at least two solutions to fit a line.")

    # linear least squares: V = m*c + b
    m, b = np.polyfit(c, v, 1)
    pred = m * c + b
    ss_res = float(np.sum((v - pred) ** 2))
    ss_tot = float(np.sum((v - v.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")

    print(f"Fit:  V = {m:.5f} * c + {b:.5f}     (c in g/L, V in volts)")
    print(f"R²  = {r2:.4f}")
    print(f"Sensitivity: {m * 1000:.2f} mV per g/L NaCl")
    if m:
        print(f"Inverse (estimate concentration): c = (V - {b:.4f}) / {m:.5f}")

    fig, ax = plt.subplots(figsize=(7.5, 5))
    xs = np.linspace(c.min(), c.max(), 100)
    ax.plot(xs, m * xs + b, color="#2E5FD0", lw=1.8,
            label=f"V = {m:.4f}·c + {b:.3f}\nR² = {r2:.3f}")
    ax.scatter(c, v, color="#0E2A4E", zorder=5, s=45)
    if "note" in df.columns:
        for ci, vi, note in zip(c, v, df["note"].fillna("")):
            ax.annotate(str(note), (ci, vi), textcoords="offset points",
                        xytext=(8, -4), fontsize=8, color="#5B6675")

    ax.set_xlabel("NaCl concentration (g/L)")
    ax.set_ylabel("compensated voltage (V)")
    ax.set_title("AquaAlert — TDS sensor calibration (NaCl)")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=150)
    print(f"Saved curve -> {args.out}")
    plt.show()


if __name__ == "__main__":
    main()
