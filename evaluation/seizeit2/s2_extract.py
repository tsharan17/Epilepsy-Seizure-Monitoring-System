"""SeizeIT2 (OpenNeuro ds005873, CC0) -> compact per-second features for the device study.

EEG: each behind-the-ear channel -> nominal device front-end model (0.5-40 Hz, x1000,
     200 Hz, 12-bit) -> line-by-line port of the shipped ESP32 firmware loop
     -> per-second mean of the firmware deviation d (the DEV-BR input) + shipped alarms.
MOV: back-of-neck Sensor Dot (head-borne, closest to a headband IMU), 25 Hz:
     acc_act  = per-second mean of ||a - EMA_1s(a)||  (high-passed acceleration)
     gyr_act  = per-second mean of ||omega||
     rhythm   = share of 2-7 Hz power in the last 4 s of ||a - EMA(a)|| (clonic rhythm)
     All three are computable on an ESP32 from an MPU9250 decimated to 25 Hz.
usage: python s2_extract.py OUTDIR [--workers 2]
"""
import json, os, re, sys, time, urllib.request, tempfile, traceback
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np

EV = Path(__file__).resolve().parent.parent   # evaluation/ (chbmit, detectors, scoring, rigor, run_eval)
sys.path.insert(0, str(EV))
S3 = "https://s3.amazonaws.com/openneuro.org"
DS = "ds005873"


def ls(prefix):
    keys, marker = [], ""
    while True:
        u = f"{S3}?prefix={prefix}&marker={marker}"
        x = urllib.request.urlopen(u, timeout=60).read().decode()
        k = re.findall(r"<Key>(.*?)</Key>", x)
        keys += k
        if "<IsTruncated>true" not in x or not k:
            return keys
        marker = k[-1]


def get(key, dst):
    for a in range(4):
        try:
            urllib.request.urlretrieve(f"{S3}/{key}", dst); return True
        except Exception:
            time.sleep(3 * (a + 1))
    return False


def ema_hp(x, alpha):
    from scipy.signal import lfilter
    lp = lfilter([alpha], [1, -(1 - alpha)], x, axis=-1, zi=None) if False else None
    y = np.empty_like(x); b = x[..., 0].copy()
    # vectorised EMA via lfilter with initial state = first sample
    from scipy.signal import lfilter as lf
    zi = (1 - alpha) * x[..., :1]
    lp = lf([alpha], [1, -(1 - alpha)], x, axis=-1, zi=zi)[0]
    return x - lp


def per_sec(v, fs, n):
    m = min(len(v) // fs, n)
    out = np.full(n, np.nan, np.float32)
    out[:m] = v[: m * fs].reshape(m, fs).mean(1)
    return out


def motion_feats(M, n):
    fs = 25
    a = M[0:3]; g = M[3:6]
    hp = ema_hp(a, 1 / 25)
    mag = np.sqrt((hp ** 2).sum(0))
    acc_act = per_sec(mag, fs, n)
    gyr_act = per_sec(np.sqrt((g ** 2).sum(0)), fs, n)
    # rhythmicity: 4-s window ending at each second, Hann, share of 2-7 Hz in 0.5-12 Hz
    m = len(mag) // fs
    rh = np.full(n, np.nan, np.float32)
    W = 100
    if m >= 4:
        idx = np.arange(4, min(m, n) + 1) * fs
        seg = np.stack([mag[i - W:i] for i in idx])
        seg = seg - seg.mean(1, keepdims=True)
        P = np.abs(np.fft.rfft(seg * np.hanning(W), axis=1)) ** 2
        f = np.fft.rfftfreq(W, 1 / fs)
        num = P[:, (f >= 2) & (f <= 7)].sum(1); den = P[:, (f >= 0.5) & (f <= 12)].sum(1) + 1e-12
        rh[3:3 + len(idx)] = (num / den)[: n - 3]
    return acc_act, gyr_act, rh


def process(job):
    key_eeg, key_mov, key_ev, out = job
    name = Path(key_eeg).name.replace("_eeg.edf", "")
    dst = Path(out) / "feat" / f"{name}.npz"
    if dst.exists():
        return None
    import pyedflib
    from chbmit import to_device_adc
    from detectors import run_firmware_detector
    from run_eval import alarm_times
    t0 = time.time()
    with tempfile.TemporaryDirectory(dir=Path(out) / "tmp") as td:
        fe, fm, fv = Path(td) / "e.edf", Path(td) / "m.edf", Path(td) / "ev.tsv"
        ok = get(key_eeg, fe) and get(key_ev, fv)
        if not ok:
            return dict(run=name, error="download")
        mov_ok = key_mov is not None and get(key_mov, fm)
        rows = [l.split("\t") for l in fv.read_text().splitlines()]
        hdr = rows[0]; rows = rows[1:]
        H = {h: i for i, h in enumerate(hdr)}
        sz = [dict(on=float(r[H["onset"]]), dur=float(r[H["duration"]]), type=r[H["eventType"]],
                   vig=r[H["vigilance"]] if "vigilance" in H else "n/a")
              for r in rows if r[H["eventType"]].startswith("sz")]
        e = pyedflib.EdfReader(str(fe))
        labs = e.getSignalLabels(); fs = int(e.getSampleFrequency(0)); dur = e.getFileDuration()
        n = int(dur)
        res = dict(run=name, duration_s=float(dur), seizures=sz, eeg_labels=labs, fs=fs)
        arrs = {}
        for ci, lab in enumerate(labs[:2]):
            uv = e.readSignal(ci)
            adc = to_device_adc(uv, fs)
            ncal, t, st, trace = run_firmware_detector(adc)
            d = trace[1].astype(np.float32)
            k = len(d) // 200
            dev = np.full(n, np.nan, np.float32)
            # firmware sample i sits at time (i + ncal)/200
            off = ncal // 200
            ds = d[: k * 200].reshape(k, 200).mean(1)
            m = min(k, n - off)
            dev[off:off + m] = ds[:m]
            arrs[f"dev{ci}"] = dev
            res[f"fw{ci}"] = dict(seizure_alarms=alarm_times(t, st, "seizure"), any_alarms=alarm_times(t, st, "any"))
            res[f"clip{ci}"] = float(np.mean((adc == 0) | (adc == 4095)))
            del uv, adc, trace, d
        e.close()
        if mov_ok:
            try:
                em = pyedflib.EdfReader(str(fm))
                ml = em.getSignalLabels()
                idx = [ml.index(f"EEG SD {c}") for c in ("ACC X", "ACC Y", "ACC Z", "GYR A", "GYR B", "GYR C")]
                M = np.array([em.readSignal(i) for i in idx]); em.close()
                a, g, r = motion_feats(M, n)
                arrs.update(acc=a, gyr=g, rhy=r)
                res["mov"] = True
            except Exception as ex:
                res["mov"] = False; res["mov_err"] = str(ex)[:200]
        else:
            res["mov"] = False
        np.savez_compressed(dst, **arrs)
    res["secs"] = round(time.time() - t0, 1)
    return res


def main():
    out = Path(sys.argv[1]); (out / "feat").mkdir(parents=True, exist_ok=True); (out / "tmp").mkdir(exist_ok=True)
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 2
    lst = out / "keys.json"
    if lst.exists():
        keys = json.loads(lst.read_text())
    else:
        keys = []
        for s in range(1, 126):
            keys += ls(f"{DS}/sub-{s:03d}/")
        lst.write_text(json.dumps(keys))
    ks = set(keys)
    jobs = []
    for k in keys:
        if k.endswith("_eeg.edf"):
            base = k[: -len("_eeg.edf")]
            mv = base.replace("/eeg/", "/mov/") + "_mov.edf"
            ev = base + "_events.tsv"
            if ev in ks:
                jobs.append((k, mv if mv in ks else None, ev, str(out)))
    print(len(jobs), "runs", flush=True)
    meta = out / "meta.jsonl"
    with ProcessPoolExecutor(workers) as ex, open(meta, "a") as fo:
        futs = [ex.submit(process, j) for j in jobs]
        for i, f in enumerate(as_completed(futs)):
            try:
                r = f.result()
            except Exception:
                r = dict(error=traceback.format_exc()[-400:])
            if r is not None:
                fo.write(json.dumps(r) + "\n"); fo.flush()
            if i % 10 == 0:
                print(i, time.strftime("%H:%M:%S"), r and r.get("secs"), flush=True)


if __name__ == "__main__":
    main()
