"""
CHB-MIT loading + Vera front-end simulation.

Data files are produced by `fetch_chbmit.js` (run in a browser on the PhysioNet
S3 mirror): for every EDF it stores only the FP1-F7 / FP2-F8 channels as raw
little-endian int16 digital values (`<rec>.ch.bin`, interleaved [n, n_ch]) plus
the EDF calibration header (`<rec>.ch.json`).  Nothing else is altered.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

# ── Vera analog front-end model (see README / PIN_CONNECTIONS) ───────────────
FRONTEND_GAIN = 1000.0      # EXG BioAmp Pill gain
ADC_VREF = 3.3              # ESP32 ADC full scale (V), 12-bit
ADC_BITS = 12
ADC_MID = 2 ** (ADC_BITS - 1)   # single-supply mid-rail bias -> 2048
DEVICE_FS = 200             # firmware samples at ~200 Hz (delay(5))


@dataclass
class Record:
    case: str
    name: str
    fs: float
    uv: dict          # channel label -> float32 µV array at native fs
    seizures: list    # [(onset_s, offset_s), ...]

    @property
    def duration_s(self) -> float:
        return len(next(iter(self.uv.values()))) / self.fs


def parse_summary(path: Path) -> dict:
    """Return {edf_name: [(onset, offset), ...]} for every file in a summary."""
    txt = Path(path).read_text(errors="replace")
    out = {}
    for block in re.split(r"File Name:\s*", txt)[1:]:
        name = block.split()[0].strip()
        starts = [int(x) for x in re.findall(r"Seizure\s*\d*\s*Start Time:\s*(\d+)", block)]
        ends = [int(x) for x in re.findall(r"Seizure\s*\d*\s*End Time:\s*(\d+)", block)]
        n = re.search(r"Number of Seizures in File:\s*(\d+)", block)
        n = int(n.group(1)) if n else len(starts)
        if len(starts) != n or len(ends) != n:
            raise ValueError(f"{path}: seizure count mismatch for {name}")
        out[name] = list(zip(starts, ends))
    return out


def load_record(data_dir: Path, case: str, name: str, seizures) -> Record:
    meta = json.loads((data_dir / f"{name}.ch.json").read_text())
    raw = np.fromfile(data_dir / f"{name}.ch.bin", dtype="<i2")
    nch = len(meta["labels"])
    raw = raw.reshape(-1, nch).astype(np.float64)
    uv = {}
    for i, lab in enumerate(meta["labels"]):
        pmin, pmax = meta["phys_min"][i], meta["phys_max"][i]
        dmin, dmax = meta["dig_min"][i], meta["dig_max"][i]
        gain = (pmax - pmin) / (dmax - dmin)
        x = (raw[:, i] - dmin) * gain + pmin
        unit = meta["dim"][i].lower()
        if unit in ("mv",):
            x = x * 1e3
        elif unit in ("v",):
            x = x * 1e6
        uv[lab.upper()] = x.astype(np.float32)
    return Record(case, name, float(meta["fs"]), uv, list(seizures))


FRONTEND_BAND = (0.5, 40.0)   # EXG BioAmp Pill pass-band per the Vera circuit diagram


def frontend_filter(uv: np.ndarray, fs: float, band=FRONTEND_BAND) -> np.ndarray:
    """Causal model of the analog pass-band: 1st-order HP + 2nd-order Butterworth LP."""
    if band is None:
        return uv
    from scipy.signal import butter, lfilter
    lo, hi = band
    b, a = butter(1, lo, btype="highpass", fs=fs)
    y = lfilter(b, a, uv)
    b, a = butter(2, hi, btype="lowpass", fs=fs)
    return lfilter(b, a, y)


def to_device_adc(uv: np.ndarray, fs_in: float, gain: float = FRONTEND_GAIN,
                  band=FRONTEND_BAND, fs_out: float = DEVICE_FS, vref: float = ADC_VREF,
                  clip_hi_v: float | None = None) -> np.ndarray:
    """µV at fs_in  ->  integer ESP32 ADC codes at 200 Hz, as Vera would see them.

    analog pass-band (optional) -> resample (polyphase, anti-aliased) -> ×gain
    -> +mid-rail -> quantise -> clip.
    """
    from fractions import Fraction
    x = frontend_filter(uv.astype(np.float64), fs_in, band)
    fr = Fraction(fs_out / fs_in).limit_denominator(1000)
    x = resample_poly(x, fr.numerator, fr.denominator)
    volts = 1.65 + x * 1e-6 * gain                  # BioAmp output around mid-supply (3.3 V / 2)
    if clip_hi_v is not None:                       # e.g. LM358 output/common-mode ceiling
        volts = np.minimum(volts, clip_hi_v)
    codes = np.round(volts / (vref / 2 ** ADC_BITS))
    return np.clip(codes, 0, 2 ** ADC_BITS - 1).astype(np.int32)


def discover(data_root: Path):
    """Yield (case, edf_name, seizures, data_dir) for every extracted record."""
    data_root = Path(data_root)
    for summ in sorted(data_root.glob("chb*-summary.txt")):
        case = summ.name.split("-")[0]
        table = parse_summary(summ)
        for edf, sz in table.items():
            name = edf.replace(".edf", "")
            if (data_root / f"{name}.ch.json").exists():
                yield case, name, sz, data_root
