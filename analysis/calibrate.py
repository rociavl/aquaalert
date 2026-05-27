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

Default fit is *slope-only* through the origin (V = m·c), paired with the
firmware's auto-tare so 0 ppm reads exactly 0 in the field. Pass
`--with-intercept` to also overlay the OLS fit (V = m·c + b) for comparison.

Reports R², sensitivity, repeatability (SD / CV), residual SD, LOD / LOQ,
and saves the curve to ../docs for the report.

Examples
--------
    python calibrate.py                       # slope-only (default)
    python calibrate.py --with-intercept      # overlay OLS for comparison
    python calibrate.py --weighted            # weighted slope-only (1/c²)
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
ERR_LABEL = {"sd": "SD", "sem": "SEM", "ci": "95% CI", "pred": "pred. error"}


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
    ap.add_argument("--error", choices=["sd", "sem", "ci", "pred"], default="sd",
                    help="error bars: sd (spread), sem (SD/sqrt n), ci (95%% t-interval), "
                         "pred (|residual to the fitted line| — the prediction error)")
    ap.add_argument("--err-magnify", type=float, default=1.0,
                    help="exaggerate the curve's error bars by this factor so they "
                         "are visible (labelled on the plot); the lower panel stays 1:1")
    ap.add_argument("--weighted", action="store_true",
                    help="also fit weighted least squares (1/c^2 weights) and compare; "
                         "recommended here because the variance grows with concentration")
    ap.add_argument("--with-intercept", action="store_true",
                    help="also fit an ordinary least-squares line with intercept and "
                         "overlay it for comparison against the default slope-only fit")
    ap.add_argument("--show-saturated", action="store_true",
                    help="also plot the excluded saturated points")
    ap.add_argument("--no-bands", action="store_true",
                    help="hide the HydroSense salivary hydration bands")
    ap.add_argument("--simple", action="store_true",
                    help="render just the calibration curve (no SD / error panels) — "
                         "use for the presentation / pitch slide")
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

    # --- fit over the individual in-fit measurements (honest scatter) ---
    c = fit_df[conc_col].to_numpy(float)
    v = fit_df[SIGNAL].to_numpy(float)
    if len(c) < 2:
        sys.exit("Need at least two in-fit measurements to fit a line.")
    n = len(c)

    # primary slope-only slope (needed up front for the "pred" error-bar mode)
    m0 = float(np.sum(c * v) / np.sum(c ** 2))

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
        elif args.error == "ci":
            a["err"] = a["n"].apply(lambda nn: tcrit(int(nn))) * sem
        else:  # pred: |observed mean V - fitted V|, per concentration
            a["err"] = (a["mean"] - m0 * a[conc_col]).abs()
        return a.sort_values(conc_col)

    fit_agg = aggregate(fit_df)
    cv = (fit_agg["std"] / fit_agg["mean"]).replace([np.inf, -np.inf], np.nan) * 100
    elabel = ERR_LABEL[args.error]

    # --- PRIMARY FIT: slope-only through the origin (V = m·c) ---
    # m0 already computed above (needed by aggregate); finish the stats here.
    ss_res0 = float(np.sum((v - m0 * c) ** 2))
    r2_0 = 1.0 - ss_res0 / float(np.sum(v ** 2))              # uncentered R²
    s_yx0 = float(np.sqrt(ss_res0 / (n - 1)))                 # 1 param -> df = n-1
    s_m0 = float(np.sqrt(s_yx0 ** 2 / np.sum(c ** 2)))
    s_x0_0 = float(s_yx0 / abs(m0) * np.sqrt(1.0 + 1.0 / n))
    lod0, loq0 = 3.3 * s_yx0 / abs(m0), 10.0 * s_yx0 / abs(m0)
    dofw = fit_agg["n"] - 1
    s_pool = float(np.sqrt(np.sum(dofw * fit_agg["std"] ** 2) / np.sum(dofw)))

    print(f"Slope-only fit over {n} measurements in {len(fit_agg)} solutions "
          f"({c.min():.0f}–{c.max():.0f} {unit}):")
    print(f"  V = {m0:.6f} * c     (intercept forced to 0; tare handles the offset)")
    print(f"  R²_uncentered = {r2_0:.4f}")
    print(f"  sensitivity   = {m0 * 1000:.3f} mV per {unit}")
    print(f"  repeatability: mean SD = {fit_agg['std'].mean() * 1000:.1f} mV, "
          f"mean CV = {cv.mean():.1f} %")
    print(f"  error bars shown = {elabel} (range {fit_agg['err'].min()*1000:.1f}"
          f"–{fit_agg['err'].max()*1000:.1f} mV)")
    print(f"  inverse: c = (V - V_blank) / {m0:.6f}     (V_blank measured at boot)")
    if len(excl_df):
        lo = excl_df[conc_col].min()
        print(f"  excluded {len(excl_df)} saturated measurements (>= {lo:.0f} {unit})")
    print("  --- regression statistics ---")
    print(f"  residual SD s(y/x) = {s_yx0*1000:.1f} mV  (df = {n-1})")
    print(f"  pooled replicate SD = {s_pool*1000:.1f} mV")
    print(f"  slope m = {m0:.6f} ± {s_m0:.6f} V/{unit}")
    print(f"  prediction uncertainty s_x0 ≈ ±{s_x0_0:.0f} {unit} per single reading")
    print(f"  LOD = {lod0:.0f} {unit},  LOQ = {loq0:.0f} {unit}")

    # --- prediction error: back-calc concentration from V with V = m·c ---
    c_hat = v / m0                                     # per-measurement prediction
    err_ppm = c_hat - c                                # signed error in ppm
    err_pct = np.where(c > 0, err_ppm / c * 100, np.nan)
    day_col = (fit_df["day"].to_numpy() if "day" in fit_df.columns
               else np.ones_like(c, dtype=int))
    err_df = (pd.DataFrame({"c": c, "c_hat": c_hat, "err": err_ppm,
                            "err_pct": err_pct, "day": day_col})
                .groupby(["c", "day"], as_index=False)
                .agg(c_hat_mean=("c_hat", "mean"),
                     c_hat_sd  =("c_hat", "std"),
                     err_mean  =("err", "mean"),
                     err_pct_mean=("err_pct", "mean"),
                     n=("c", "size")))
    err_df["c_hat_sd"] = err_df["c_hat_sd"].fillna(0.0)
    rmse = float(np.sqrt(np.mean(err_ppm ** 2)))
    mae = float(np.mean(np.abs(err_ppm)))
    band = (c >= 200) & (c <= 500)
    mae_band = float(np.mean(np.abs(err_ppm[band]))) if band.any() else float("nan")
    print("  --- prediction error (back-calculated concentration from V) ---")
    print(f"     true     predicted          error      error")
    print(f"    (ppm)   (ppm) mean ± SD      (ppm)       (%)")
    for _, r in err_df.iterrows():
        print(f"    {r['c']:5.0f}    {r['c_hat_mean']:6.1f} ± {r['c_hat_sd']:4.1f}     "
              f"{r['err_mean']:+7.1f}    {r['err_pct_mean']:+6.1f}")
    print(f"  overall: MAE = {mae:.1f} ppm,  RMSE = {rmse:.1f} ppm")
    print(f"  hydrated band 200–500 ppm: MAE = {mae_band:.1f} ppm")

    # --- OPTIONAL OLS COMPARISON (V = m·c + b) ---
    m = b = r2 = s_yx = s_m = s_b = s_x0 = sign = None
    if args.with_intercept:
        m, b = (float(x) for x in np.polyfit(c, v, 1))
        ss_res = float(np.sum((v - (m * c + b)) ** 2))
        ss_tot = float(np.sum((v - v.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")
        Sxx = float(np.sum((c - c.mean()) ** 2))
        s_yx = float(np.sqrt(ss_res / (n - 2)))
        s_m = float(np.sqrt(s_yx ** 2 / Sxx))
        s_b = float(s_yx * np.sqrt(np.sum(c ** 2) / (n * Sxx)))
        s_x0 = float((s_yx / abs(m)) * np.sqrt(1.0 + 1.0 / n))
        sign = "-" if b < 0 else "+"
        t_b = b / s_b
        verdict = ("OLS preferred (intercept is real)" if abs(t_b) > 2
                   else "slope-only is justified (intercept ≈ 0)")
        print("  --- OLS comparison (with intercept) ---")
        print(f"  V = {m:.6f} * c {sign} {abs(b):.4f}")
        print(f"  R² = {r2:.4f},  s(y/x) = {s_yx*1000:.1f} mV  (df = {n-2})")
        print(f"  slope     m = {m:.6f} ± {s_m:.6f} V/{unit}")
        print(f"  intercept b = {b:.4f} ± {s_b:.4f} V   "
              f"[t = {t_b:.2f}, df = {n-2}  →  {verdict}]")
        print(f"  prediction uncertainty s_x0 ≈ ±{s_x0:.0f} {unit} per single reading")

    # --- weighted least squares thru origin (1/c^2): better for heteroscedasticity ---
    mw0 = None
    if args.weighted:
        w = 1.0 / c                                          # polyfit minimises (w*r)^2
        # weighted slope thru origin: m = Σ w² c v / Σ w² c²
        mw0 = float(np.sum((w ** 2) * c * v) / np.sum((w ** 2) * c ** 2))

        def conc_err_slope(mm):
            pe = np.abs((v / mm - c) / c) * 100
            band = (c >= 200) & (c <= 500)
            return pe.mean(), (pe[band].mean() if band.any() else float("nan"))

        u_all, u_hy = conc_err_slope(m0)
        w_all, w_hy = conc_err_slope(mw0)
        print("  --- weighted slope-only (1/c²) vs unweighted slope-only ---")
        print(f"  weighted: V = {mw0:.6f} * c")
        print(f"  mean |error| back-calculated concentration:")
        print(f"      overall          OLS-0 {u_all:4.1f} %  ->  WLS-0 {w_all:4.1f} %")
        print(f"      hydrated 200-500 OLS-0 {u_hy:4.1f} %  ->  WLS-0 {w_hy:4.1f} %")

    # figure layout: simple = one panel for slides; default = 3-panel diagnostic
    if args.simple:
        fig, ax = plt.subplots(figsize=(8.4, 5.6))
        axb = axc = None
    else:
        fig, (ax, axb, axc) = plt.subplots(3, 1, figsize=(7.8, 8.0), sharex=True,
                                           gridspec_kw={"height_ratios": [3, 1, 1.2]})

    xs = np.linspace(0, c.max(), 100)
    ax.plot(xs, m0 * xs, color="#2E5FD0", lw=1.8, zorder=3,
            label=f"V = {m0:.4f}·c\nR²_unc = {r2_0:.3f}")
    if args.weighted and mw0 is not None:
        ax.plot(xs, mw0 * xs, color="#E5402F", lw=1.4, ls="--", zorder=3,
                label=f"WLS 1/c²: V = {mw0:.4f}·c")
    if args.with_intercept and m is not None:
        ax.plot(xs, m * xs + b, color="#6B7A99", lw=1.2, ls=":", zorder=3,
                label=f"OLS comparison: V = {m:.4f}·c {sign} {abs(b):.3f}")

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
    if args.simple:
        title = "AquaAlert — TDS sensor calibration (NaCl)"
        ax.set_xlabel(f"reference concentration ({unit})")
    else:
        title = f"AquaAlert — TDS sensor calibration (NaCl), slope-only · mean ± {elabel}"
    if mag != 1:
        title += f"  (error bars ×{mag:g})"
    ax.set_title(title)
    ax.grid(True, alpha=0.2)
    ax.legend(loc="lower right", frameon=False)

    if axb is not None:
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
        axb.set_ylabel(f"± {elabel} (mV)")
        axb.grid(True, alpha=0.2)
        axb.legend(loc="upper left", frameon=False, fontsize=8)

    if axc is not None:
        for d_, grp_ in err_df.groupby("day"):
            color, mk = markers.get(int(d_), ("#0E2A4E", "o"))
            axc.errorbar(grp_["c"], grp_["err_mean"], yerr=grp_["c_hat_sd"], fmt=mk,
                         color=color, ms=4, lw=0, elinewidth=1.0, capsize=2,
                         ecolor=color, zorder=5)
        axc.axhline(0, color="#0E2A4E", lw=1, alpha=0.5)
        axc.axhline(mae, color="#888", ls=":", lw=1, label=f"MAE = {mae:.1f} ppm")
        axc.axhline(-mae, color="#888", ls=":", lw=1)
        axc.set_xlabel(f"reference concentration ({unit})  ·  bands: HydroSense salivary thresholds")
        axc.set_ylabel("prediction error (ppm)")
        axc.grid(True, alpha=0.2)
        axc.legend(loc="upper right", frameon=False, fontsize=8)

    fig.tight_layout()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=150)
    print(f"Saved curve -> {args.out}")
    plt.show()


if __name__ == "__main__":
    main()
