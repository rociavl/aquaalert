#!/usr/bin/env python3
"""Split a long TDS capture into per-solution plateaus.

During the calibration experiment the probe is dipped into each solution
in turn, with dry gaps (voltage ≈ 0) in between. This tool finds those
in-solution segments and reports the stable plateau voltage of each, so
you can map segment -> NaCl concentration and build calibration.csv.

Capture columns (from aquaalert_tds_calibration firmware):
    timestamp_ms,voltage_V,voltage_compensated_V,tds_ppm_uncalibrated

Examples
--------
    python segment_captures.py ../data/sensor_data_2.txt
    python segment_captures.py ../data/sensor_data_2.txt --csv ../data/segments_day2.csv
"""
from __future__ import annotations

import argparse
import statistics as st
import sys
from pathlib import Path


def load(path: Path):
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            p = line.split(",")
            if len(p) < 4 or not p[0].replace(".", "").isdigit():
                continue
            try:
                rows.append((int(float(p[0])), float(p[1]), float(p[2]), float(p[3])))
            except ValueError:
                continue
    return rows


def segment(rows, thr: float, min_len: int):
    segs, cur = [], []
    for r in rows:
        if r[2] > thr:           # voltage_compensated_V above the dry threshold
            cur.append(r)
        else:
            if len(cur) >= min_len:
                segs.append(cur)
            cur = []
    if len(cur) >= min_len:
        segs.append(cur)
    return segs


def plateau(seg, tail_frac: float = 0.6):
    """Mean of the stable tail of a segment (skips the immersion transient)."""
    v = [r[2] for r in seg]
    stable = v[int(len(v) * (1 - tail_frac)):]
    return st.mean(stable), (st.pstdev(stable) if len(stable) > 1 else 0.0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture", type=Path)
    ap.add_argument("--thr", type=float, default=0.05, help="dry/in-solution voltage threshold")
    ap.add_argument("--min-len", type=int, default=8, help="min rows to count as a segment")
    ap.add_argument("--csv", type=Path, help="also write the segment table here")
    args = ap.parse_args()

    if not args.capture.exists():
        sys.exit(f"{args.capture} not found.")

    rows = load(args.capture)
    if not rows:
        sys.exit("No numeric rows parsed — is this a capture file?")
    segs = segment(rows, args.thr, args.min_len)

    print(f"{args.capture.name}: {len(rows)} rows, "
          f"{rows[0][0]/1000:.0f}–{rows[-1][0]/1000:.0f}s, {len(segs)} segments\n")
    header = f"{'seg':>3}  {'t_start_s':>9}  {'t_end_s':>8}  {'n':>4}  {'V_plateau':>9}  {'std':>6}"
    print(header)
    print("-" * len(header))
    table = []
    for i, s in enumerate(segs, 1):
        mean, sd = plateau(s)
        print(f"{i:>3}  {s[0][0]/1000:>9.1f}  {s[-1][0]/1000:>8.1f}  {len(s):>4}  {mean:>9.4f}  {sd:>6.4f}")
        table.append((i, round(s[0][0]/1000, 1), round(s[-1][0]/1000, 1), len(s), round(mean, 4), round(sd, 4)))

    if args.csv:
        import csv
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["segment", "t_start_s", "t_end_s", "n", "voltage_compensated_V", "std_V"])
            w.writerows(table)
        print(f"\nWrote {args.csv}")
    print("\nNext: map each segment to its NaCl concentration in data/calibration.csv, "
          "then run calibrate.py")


if __name__ == "__main__":
    main()
