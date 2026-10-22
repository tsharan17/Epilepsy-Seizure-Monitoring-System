"""v5_telemetry.py — log the once-per-second "# [V5]" lines of firmware v5.

The v4 analyzer (seizure_monitor.py) is unchanged and keeps working: it skips
every line that starts with '#'.  Run this instead of (or next to, via a serial
splitter) the analyzer to record the on-device multimodal detector:

    python v5_telemetry.py COM5            # Windows
    python v5_telemetry.py /dev/ttyUSB0    # Linux

Writes v5_log_<date>.csv with: time, fs, dev, eegR, acc, gyr, rhy, movR, event, conv
(event: 0 none, 1 EEG, 2 motion, 3 both; conv: 1 = convulsive alarm).  Requires pyserial.
"""
import csv, re, sys, time
from datetime import datetime

PAT = re.compile(r"#\s*\[V5\]\s+(.*)")


def parse_v5(line: str):
    m = PAT.match(line.strip())
    if not m:
        return None
    out = {}
    for kv in m.group(1).split():
        k, _, v = kv.partition("=")
        try:
            out[k] = float(v) if v.lower() != "nan" else float("nan")
        except ValueError:
            pass
    return out


def main():
    import serial
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
    ser = serial.Serial(port, 115200, timeout=2)
    fn = f"v5_log_{datetime.now():%Y%m%d_%H%M%S}.csv"
    cols = ["fs", "dev", "eegR", "acc", "gyr", "rhy", "movR", "event", "conv"]
    with open(fn, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["time"] + cols)
        print("logging to", fn)
        while True:
            raw = ser.readline().decode(errors="replace")
            d = parse_v5(raw)
            if d is None:
                if raw.startswith("# [IMU]") or raw.startswith("# [STATE]"):
                    print(raw.strip())
                continue
            w.writerow([f"{time.time():.1f}"] + [d.get(c, "") for c in cols]); f.flush()
            if d.get("conv", 0):
                print(f"{datetime.now():%H:%M:%S}  CONVULSIVE ALARM  eegR={d.get('eegR')}  movR={d.get('movR')}")
            elif d.get("event", 0):
                src = {1: "EEG", 2: "MOTION", 3: "EEG+MOTION"}.get(int(d["event"]), "?")
                print(f"{datetime.now():%H:%M:%S}  event ({src})  eegR={d.get('eegR')}  movR={d.get('movR')}")


if __name__ == "__main__":
    main()
