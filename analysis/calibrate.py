#!/usr/bin/env python3
"""Build the NaCl calibration curve from the TDS sensor's compensated voltage.

The DFRobot ppm polynomial was fitted at 5 V, so on the ESP32 (3.3 V) the
firmware's ppm value is unreliable. Calibration therefore relates the
temperature-compensated electrode *voltage* to the known reference
concentration of each solution.

Reads ../data/calibration_replicates.csv (one row per measurement):

    concentration_ppm,voltage_compensated_V,day,in_fit,note
    180,0.380,1,1,
    180,0.389,1,1,
    180,0.386,1,1,
    ...

Replicates of the same concentration are averaged; the plot shows the mean
with error bars (--error sd|sem|ci). Because repeatability is high the bars
are tiny on the V axis, so a lower panel plots the spread (in mV) per
concentration where it is actually visible. The optional `in_fit` column
(1/0) excludes saturated points from the linear fit while still letting them
be plotted. Also accepts `concentration_g_L`.

Fits V = m·c + b over the in-fit measurements, reports R², sensitivity and
repeatability (mean SD / CV), and saves the curve to ../docs for the report.

Examples
--------
    python calibrate.py
    python calibrate.py --error sem
    python calibrate.py --show-saturated
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
REPLICATES_CSV = ROOT / "data" / "calibration_replicates.csv"
MEANS_CSV = ROOT / "data" / "calibration.csv"
DEFAULT_CSV = REPLICATES_CSV if REPLICATES_CSV.exists() else MEANS_CSV
SIGNAL = "voltage_compensated_V"
ERR_LABEL = {"sd": "SD", "sem": "SEM", "ci": "95% CI"}


def tcrit(n: int, conf: float = 0.95) -> float:
    """Two-sided Student-t critical value for n replicates (df = n-1)."""
    df = n - 1
    if df < 1:
        return 0.0
    try:
        from scipy import stats
        return float(stats.t.ppf(1 - (1 - conf) / 2, df))
    except Exception:
        table = {1: 12.71, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
                 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}
        return table.get(df, 1.96)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "calibration_curve.png")
    ap.add_argument("--error", choices=["sd", "sem", "ci"], default="sd",
                    help="error bars: sd (spread), sem (SD/sqrt n), ci (95%% t-interval)")
    ap.add_argument("--err-magnify", type=float, default=1.0,
                    help="exaggerate the curve's error bars by this factor so they "
                         "are visible (labelled on the plot); the lower panel stays 1:1")
    ap.add_argument("--show-saturated", action="store_true",
                    help="also plot the excluded saturated points")
    ap.add_argument("--no-bands", action="store_true",
                    help="hide the HydroSense salivary hydration bands")
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

    def aggregate(d: pd.DataFrame) -> pd.DataFrame:
        """Mean / SD / n (+ chosen error bar) of the signal per concentration."""
        keys = [conc_col] + (["day"] if "day" in d.columns else [])
        a = (d.groupby(keys, as_index=False)[SIGNAL]
               .agg(mean="mean", std="std", n="count"))
        a["std"] = a["std"].fillna(0.0)        # single-replicate points -> SD 0
        sem = a["std"] / np.sqrt(a["n"].clip(lower=1))
        if args.error == "sd":
            a["err"] = a["std"]
        elif args.error == "sem":
            a["err"] = sem
        else:  # ci
            a["err"] = a["n"].apply(lambda nn: tcrit(int(nn))) * sem
        return a.sort_values(conc_col)

    # --- fit over the individual in-fit measurements (honest scatter) ---
    c = fit_df[conc_col].to_numpy(float)
    v = fit_df[SIGNAL].to_numpy(float)
    if len(c) < 2:
        sys.exit("Need at least two in-fit measurements to fit a line.")

    m, b = np.polyfit(c, v, 1)            # V = m*c + b
    pred = m * c + b
    ss_res = float(np.sum((v - pred) ** 2))
    ss_tot = float(np.sum((v - v.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")

    fit_agg = aggregate(fit_df)
    cv = (fit_agg["std"] / fit_agg["mean"]).replace([np.inf, -np.inf], np.nan) * 100

    sign = "-" if b < 0 else "+"
    elabel = ERR_LABEL[args.error]
    print(f"Fit over {len(c)} measurements in {len(fit_agg)} solutions "
          f"({c.min():.0f}–{c.max():.0f} {unit}):")
    print(f"  V = {m:.6f} * c {sign} {abs(b):.4f}     (c in {unit}, V in volts)")
    print(f"  R²  = {r2:.4f}")
    print(f"  sensitivity = {m * 1000:.3f} mV per {unit}")
    print(f"  repeatability: mean SD = {fit_agg['std'].mean() * 1000:.1f} mV, "
          f"mean CV = {cv.mean():.1f} %")
    print(f"  error bars shown = {elabel} (range {fit_agg['err'].min()*1000:.1f}"
          f"–{fit_agg['err'].max()*1000:.1f} mV)")
    if m:
        print(f"  inverse: c = (V - {b:.4f}) / {m:.6f}")
    if len(excl_df):
        lo = excl_df[conc_col].min()
        print(f"  excluded {len(excl_df)} saturated measurements (>= {lo:.0f} {unit})")

    # two stacked panels: calibration curve (top) + spread in mV (bottom)
    fig, (ax, axb) = plt.subplots(2, 1, figsize=(7.8, 6.4), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1]})

    xs = np.linspace(c.min(), c.max(), 100)
    ax.plot(xs, m * xs + b, color="#2E5FD0", lw=1.8, zorder=3,
            label=f"V = {m:.4f}·c {sign} {abs(b):.3f}\nR² = {r2:.3f}")

    markers = {1: ("#0E2A4E", "o"), 2: ("#2E5FD0", "s")}

    mag = args.err_magnify

    def plot_group(grp, color, mk, lbl, *, hollow=False, on=ax):
        on.errorbar(grp[conc_col], grp["mean"], yerr=grp["err"] * mag, fmt=mk,
                    color=color, ms=3, lw=0, elinewidth=1.0, capsize=2,
                    ecolor=color, zorder=4, label=lbl,
                    mfc=("none" if hollow else color), mec=color)

    # top panel: mean ± error, coloured by experiment day
    if "day" in fit_agg.columns:
        for d, grp in fit_agg.groupby("day"):
            color, mk = markers.get(int(d), ("#0E2A4E", "o"))
            plot_group(grp, color, mk, f"day {int(d)} (mean ± {elabel})")
    else:
        plot_group(fit_agg, "#0E2A4E", "o", f"mean ± {elabel}")

    if args.show_saturated and len(excl_df):
        ex_agg = aggregate(excl_df)
        plot_group(ex_agg, "#B23A2F", "o", "saturated (excluded)", hollow=True)
        ax.axhline(2.3, color="#B23A2F", ls=":", lw=1, alpha=0.6)
        ax.text(df[conc_col].max(), 2.31, "sensor ceiling ~2.3 V",
                ha="right", va="bottom", fontsize=8, color="#B23A2F")

    # HydroSense (IJSRSET 2025) salivary hydration bands, in ppm TDS
    if not args.no_bands and unit == "ppm":
        x0, x1 = ax.get_xlim()
        bands = [(200, 500, "#2FB457", "hydrated"),
                 (500, 700, "#F2C200", "mild"),
                 (700, 900, "#F5921E", "moderate"),
                 (900, 1e9, "#E5402F", "severe")]
        ytop = ax.get_ylim()[1]
        for lo, hi, col, lbl in bands:
            a, bb = max(lo, x0), min(hi, x1)
            if a >= bb:
                continue
            ax.axvspan(a, bb, color=col, alpha=0.08, zorder=0)
            ax.text((a + bb) / 2, ytop * 0.98, lbl, ha="center", va="top",
                    fontsize=7.5, color=col, alpha=0.9)
        ax.set_xlim(x0, x1)

    ax.set_ylabel("compensated voltage (V)")
    title = f"AquaAlert — TDS sensor calibration (NaCl), mean ± {elabel}"
    if mag != 1:
        title += f"  (error bars ×{mag:g})"
    ax.set_title(title)
    ax.grid(True, alpha=0.2)
    ax.legend(loc="lower right", frameon=False)

    # bottom panel: the spread itself, in mV, where it is actually visible
    mean_err_mv = fit_agg["err"].mean() * 1000
    for d, grp in (fit_agg.groupby("day") if "day" in fit_agg.columns
                   else [(None, fit_agg)]):
        color, mk = markers.get(int(d), ("#0E2A4E", "o")) if d is not None \
            else ("#0E2A4E", "o")
        axb.vlines(grp[conc_col], 0, grp["err"] * 1000, color=color, lw=1.2, alpha=0.6)
        axb.scatter(grp[conc_col], grp["err"] * 1000, color=color, marker=mk, s=28,
                    zorder=5)
    axb.axhline(mean_err_mv, color="#888", ls="--", lw=1,
                label=f"mean {elabel} = {mean_err_mv:.1f} mV")
    axb.set_ylim(bottom=0)
    axb.set_xlabel(f"reference concentration ({unit})  ·  bands: HydroSense salivary thresholds")
    axb.set_ylabel(f"± {elabel} (mV)")
    axb.grid(True, alpha=0.2)
    axb.legend(loc="upper left", frameon=False, fontsize=8)

    fig.tight_layout()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=150)
    print(f"Saved curve -> {args.out}")
    plt.show()


if __name__ == "__main__":
    main()
