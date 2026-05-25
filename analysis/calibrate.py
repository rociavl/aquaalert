#!/usr/bin/env python3
"""Build the NaCl calibration curve from the TDS sensor's compensated voltage.

The DFRobot ppm polynomial was fitted at 5 V, so on the ESP32 (3.3 V) the
firmware's ppm value is unreliable. Calibration therefore relates the
temperature-compensated electrode *voltage* to the known reference
concentration of each solution.

Reads ../data/calibration.csv:

    concentration_ppm,voltage_compensated_V,in_fit,note
    180,0.385,1,
    ...
    1820,2.270,0,saturated

The optional `in_fit` column (1/0) excludes saturated points from the
linear fit while still plotting them, so the working range is honest.
Also accepts `concentration_g_L` instead of `concentration_ppm`.

Fits V = m·c + b over the in-fit points, reports R² and sensitivity, and
saves the curve to ../docs for the report.

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
                 f"Create it with columns: concentration_ppm,{SIGNAL},in_fit,note")

    df = pd.read_csv(args.csv)
    conc_col = "concentration_ppm" if "concentration_ppm" in df.columns else \
               "concentration_g_L" if "concentration_g_L" in df.columns else None
    if conc_col is None or SIGNAL not in df.columns:
        sys.exit(f"Need a concentration column and '{SIGNAL}'. Found: {list(df.columns)}")
    unit = "ppm" if conc_col.endswith("ppm") else "g/L"

    df = df.sort_values(conc_col)
    if "in_fit" in df.columns:
        fit_df = df[df["in_fit"].astype(int) == 1]
        excl_df = df[df["in_fit"].astype(int) == 0]
    else:
        fit_df, excl_df = df, df.iloc[0:0]

    c = fit_df[conc_col].to_numpy(float)
    v = fit_df[SIGNAL].to_numpy(float)
    if len(c) < 2:
        sys.exit("Need at least two in-fit solutions to fit a line.")

    # linear least squares: V = m*c + b
    m, b = np.polyfit(c, v, 1)
    pred = m * c + b
    ss_res = float(np.sum((v - pred) ** 2))
    ss_tot = float(np.sum((v - v.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")

    print(f"Fit over {len(c)} points ({c.min():.0f}–{c.max():.0f} {unit}):")
    print(f"  V = {m:.6f} * c + {b:.4f}     (c in {unit}, V in volts)")
    print(f"  R²  = {r2:.4f}")
    print(f"  sensitivity = {m * 1000:.3f} mV per {unit}")
    if m:
        print(f"  inverse: c = (V - {b:.4f}) / {m:.6f}")
    if len(excl_df):
        lo = excl_df[conc_col].min()
        print(f"  excluded {len(excl_df)} saturated points (>= {lo:.0f} {unit})")

    fig, ax = plt.subplots(figsize=(7.8, 5))
    xs = np.linspace(c.min(), c.max(), 100)
    ax.plot(xs, m * xs + b, color="#2E5FD0", lw=1.8, zorder=3,
            label=f"V = {m:.4f}·c + {b:.3f}\nR² = {r2:.3f}")
    ax.scatter(c, v, color="#0E2A4E", s=46, zorder=5, label="in fit")
    if len(excl_df):
        ax.scatter(excl_df[conc_col], excl_df[SIGNAL], facecolors="none",
                   edgecolors="#B23A2F", s=46, zorder=4, label="saturated (excluded)")
        ax.axhline(2.3, color="#B23A2F", ls=":", lw=1, alpha=0.6)
        ax.text(df[conc_col].max(), 2.31, "sensor ceiling ~2.3 V",
                ha="right", va="bottom", fontsize=8, color="#B23A2F")

    ax.set_xlabel(f"reference concentration ({unit})")
    ax.set_ylabel("compensated voltage (V)")
    ax.set_title("AquaAlert — TDS sensor calibration (NaCl)")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="lower right", frameon=False)
    fig.tight_layout()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=150)
    print(f"Saved curve -> {args.out}")
    plt.show()


if __name__ == "__main__":
    main()
