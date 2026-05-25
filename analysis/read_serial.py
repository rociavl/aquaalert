#!/usr/bin/env python3
"""Capture AquaAlert sensor data from the ESP32 over USB serial into a CSV.

The firmware streams comma-separated rows at 115200 baud with a header
line (lines starting with '#' are ignored). This tool auto-detects the
board, prints readings live, and saves a timestamped CSV under ../data.

Examples
--------
    python read_serial.py                       # auto-detect, save, live print
    python read_serial.py --label nacl_10gL     # tag the output filename
    python read_serial.py --duration 30         # stop after 30 s
    python read_serial.py --port /dev/cu.usbserial-0001
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial not installed. Run:  pip install -r requirements.txt")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
# USB-serial bridges commonly found on ESP32 boards (CP210x, CH340, FTDI).
PORT_HINTS = ("usbserial", "SLAB", "wchusb", "usbmodem", "ttyUSB", "ttyACM")


def autodetect_port() -> str | None:
    ports = list(list_ports.comports())
    for p in ports:
        if any(h.lower() in p.device.lower() for h in PORT_HINTS):
            return p.device
    # fall back to the first non-Bluetooth port, if any
    for p in ports:
        if "bluetooth" not in p.device.lower():
            return p.device
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial port (auto-detected if omitted)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--label", default="capture", help="tag added to the filename")
    ap.add_argument("--duration", type=float, help="stop after N seconds")
    ap.add_argument("--out", type=Path, default=DATA_DIR, help="output directory")
    args = ap.parse_args()

    port = args.port or autodetect_port()
    if not port:
        sys.exit("No serial port found. Plug in the ESP32 or pass --port.")

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = args.out / f"{args.label}_{stamp}.csv"

    print(f"Port      : {port} @ {args.baud} baud")
    print(f"Saving to : {out_path}")
    print("Press Ctrl-C to stop.\n")

    header: list[str] | None = None
    rows = 0
    signal_col = None          # column we summarise at the end
    signal_values: list[float] = []
    t0 = time.time()

    with serial.Serial(port, args.baud, timeout=1) as ser, \
            open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        try:
            while True:
                if args.duration and (time.time() - t0) >= args.duration:
                    break
                raw = ser.readline().decode("utf-8", errors="replace").strip()
                if not raw or raw.startswith("#"):
                    continue

                fields = [x.strip() for x in raw.split(",")]

                # First non-comment line that isn't numeric -> column header.
                if header is None and not _looks_numeric(fields[0]):
                    header = ["host_time"] + fields
                    writer.writerow(header)
                    print("  ".join(header))
                    # pick the calibration-relevant signal to summarise
                    for cand in ("voltage_compensated_V", "ec_uscm", "z_mag_ohm"):
                        if cand in header:
                            signal_col = cand
                            break
                    continue

                if header is None:  # data arrived before a header; synthesise one
                    header = ["host_time"] + [f"col{i}" for i in range(len(fields))]
                    writer.writerow(header)

                writer.writerow([datetime.now().isoformat(timespec="seconds"), *fields])
                f.flush()
                rows += 1
                print(f"  {raw}")

                # track the calibration signal for the end-of-run summary
                if signal_col:
                    try:
                        signal_values.append(float(fields[header.index(signal_col) - 1]))
                    except (ValueError, IndexError):
                        pass
        except KeyboardInterrupt:
            print("\nStopped.")

    print(f"\nSaved {rows} rows to {out_path}")
    if signal_values:
        mean = sum(signal_values) / len(signal_values)
        print(f"Mean {signal_col} over capture: {mean:.4f} "
              f"(n={len(signal_values)}) — paste this into data/calibration.csv")


def _looks_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    main()
