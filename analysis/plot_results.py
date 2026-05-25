#!/usr/bin/env python3
"""Plot a captured AquaAlert run (conductance or impedance) over time.

Reads a CSV produced by read_serial.py and plots the main signal against
the device time axis. Saves a PNG next to the CSV.

Examples
--------
    python plot_results.py                       # newest CSV in ../data
    python plot_results.py ../data/nacl_10gL_20260525_173000.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import pandas as pd
    import matplotlib.pyplot as plt
except ImportError:
    sys.exit("Missing deps. Run:  pip install -r requirements.txt")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def newest_csv() -> Path:
    csvs = sorted(DATA_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime)
    csvs = [c for c in csvs if "calibration" not in c.name]
    if not csvs:
        sys.exit(f"No capture CSVs in {DATA_DIR}. Run read_serial.py first.")
    return csvs[-1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", type=Path, help="capture CSV (default: newest)")
    args = ap.parse_args()

    path = args.csv or newest_csv()
    df = pd.read_csv(path)
    print(f"Loaded {len(df)} rows from {path.name}")

    # time axis in seconds, from the device millisecond clock if present
    time_col = "timestamp_ms" if "timestamp_ms" in df.columns else \
               "t_ms" if "t_ms" in df.columns else None
    if time_col:
        t = (df[time_col] - df[time_col].iloc[0]) / 1000.0
        xlabel = "time (s)"
    else:
        t = range(len(df))
        xlabel = "sample"

    # pick the primary signal: compensated voltage for the TDS sensor
    # (the ppm polynomial is unreliable at 3.3 V), |Z| for BIA.
    if "voltage_compensated_V" in df.columns:
        y, ylabel, color = df["voltage_compensated_V"], "compensated voltage (V)", "#2E5FD0"
        title = "TDS sensor — compensated voltage"
    elif "ec_uscm" in df.columns:
        y, ylabel, color = df["ec_uscm"], "conductivity (µS/cm)", "#2E5FD0"
        title = "Salivary / ionic conductance"
    elif "z_mag_ohm" in df.columns:
        y, ylabel, color = df["z_mag_ohm"], "|Z| (Ω)", "#244FB0"
        title = "Ankle bioimpedance magnitude"
    else:
        sys.exit("CSV has no recognised signal column "
                 "(voltage_compensated_V / ec_uscm / z_mag_ohm).")

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(t, y, color=color, lw=1.6)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(f"AquaAlert — {title}")
    ax.grid(True, alpha=0.25)

    mean, std = y.mean(), y.std()
    ax.axhline(mean, color="#F5921E", ls="--", lw=1,
               label=f"mean {mean:.1f}  (σ {std:.1f})")
    ax.legend(loc="best", frameon=False)
    fig.tight_layout()

    out = path.with_suffix(".png")
    fig.savefig(out, dpi=150)
    print(f"Saved plot -> {out}")
    plt.show()


if __name__ == "__main__":
    main()
