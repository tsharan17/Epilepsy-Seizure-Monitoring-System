"""
Hardware-robustness addendum for DEV-BR (FP1-FP2).

Re-runs only the (fast) firmware stage under several front-end conditions and
evaluates DEV-BR on each, so that the paper's gain-invariance and
hardware-sensitivity statements rest on measurements rather than argument.

Conditions (all with the 0.5–40 Hz pass-band model):
  g500, g1000, g2000      amplifier gain ×500 / ×1000 / ×2000, ideal 3.3-V ADC
  g1000_clip, g2000_clip  LM358 ceiling: output cannot exceed 1.8 V (VCC − 1.5 V)
  g1000_adc31             ESP32 default 11-dB attenuation: ≈3.1-V full scale
  g1000_166Hz             loop slower than nominal: 6 ms per sample (≈166.7 Hz)

For every condition:
  • DEV-BR re-tuned by leave-one-subject-out CV (targets 1.0 and 0.5 FA/h)
  • DEV-BR with FIXED parameters (those chosen at g1000) — the invariance test
  • the shipped firmware detector's BLACKOUT alarms, for reference
  • ADC clipping fraction and median per-second deviation

usage: python hw_robustness.py --data data/chbmit --out results_hw
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chbmit import discover, load_record, to_device_adc                  # noqa: E402
from detectors import run_firmware_detector                              # noqa: E402
from scoring import score_record, alarm_times                            # noqa: E402
import personalize as P                                                  # noqa: E402
import rigor as RG                                                       # noqa: E402

CH = "FP1-FP2"
COND = {
    "g500": dict(gain=500.0), "g1000": dict(gain=1000.0), "g2000": dict(gain=2000.0),
    "g1000_clip": dict(gain=1000.0, clip_hi_v=1.8), "g2000_clip": dict(gain=2000.0, clip_hi_v=1.8),
    "g1000_adc31": dict(gain=1000.0, vref=3.1), "g1000_166Hz": dict(gain=1000.0, fs_out=1000.0 / 6.0),
}


def one(job):
    case, name, seizures, data_dir = job
    rec = load_record(Path(data_dir), case, name, seizures)
    if CH not in rec.uv:
        return None
    out = dict(case=case, record=name, seizures=seizures, duration_s=rec.duration_s, cond={})
    for cname, kw in COND.items():
        fs = kw.get("fs_out", 200.0)
        adc = to_device_adc(rec.uv[CH], rec.fs, **kw)
        ncal, t, st, trace = run_firmware_detector(adc, SAMPLE_MS=1000.0 / fs)
        d = trace[1].astype(np.float64)
        n = int(np.floor(rec.duration_s))
        sec = np.clip(((np.arange(len(d)) + ncal) / fs).astype(np.int64), 0, n - 1)
        s = np.bincount(sec, weights=d, minlength=n); c = np.bincount(sec, minlength=n)
        delta = np.where(c > 0, s / np.maximum(c, 1), np.nan)
        idx = np.where(np.isfinite(delta), np.arange(n), 0); np.maximum.accumulate(idx, out=idx)
        delta = delta[idx]
        out["cond"][cname] = dict(delta=delta.astype(np.float32).tolist(),
                                  fw_alarms=alarm_times(t, st, "seizure"),
                                  sat=float(np.mean((adc == 0) | (adc == 4095) |
                                                    ((adc >= np.round(kw["clip_hi_v"] / (kw.get("vref", 3.3) / 4096))) if kw.get("clip_hi_v") else False))))
    return out


def evaluate(recs, outdir):
    res = {}
    subjects = sorted({RG.subject(r["case"]) for r in recs})
    loso = [[i for i, r in enumerate(recs) if RG.subject(r["case"]) == u] for u in subjects]
    fixed = None
    for cname in COND:
        rows = []
        for r in recs:
            d = np.asarray(r["cond"][cname]["delta"], float)
            rows.append(dict(case=r["case"], record=r["record"], seizures=r["seizures"], duration_s=r["duration_s"],
                             S={"DEV": RG.baseline_score(d)}))
        cache = {"DEV": RG.Cache(rows, "DEV")}
        e = dict(sat=float(np.mean([r["cond"][cname]["sat"] for r in recs])),
                 median_delta=float(np.nanmedian(np.concatenate([np.asarray(r["cond"][cname]["delta"], float) for r in recs]))))
        for tgt in (1.0, 0.5):
            sc, chs = RG.cv(cache, rows, loso, tgt, ["DEV"])
            s = RG.summarise(sc, rows, B=500)
            e[f"loso_{tgt}"] = {k: s[k] for k in ("sensitivity", "sens_ci", "macro_sensitivity", "fa_per_hour", "latency_median")}
            e[f"loso_{tgt}"]["choices"] = [(c["r"], c["D"]) for c in chs]
        if cname == "g1000":
            # the single most common (r, D) chosen across LOSO folds at each target → frozen parameters
            from collections import Counter
            fixed = {}
            for tgt in (1.0, 0.5):
                fixed[tgt] = Counter(map(tuple, e[f"loso_{tgt}"]["choices"])).most_common(1)[0][0]
        res[cname] = e
        res[cname]["rows"] = rows
    for cname in COND:
        rows = res[cname].pop("rows")
        cache = RG.Cache(rows, "DEV")
        for tgt, (rr, D) in fixed.items():
            sc = RG.score_set(cache, list(range(len(rows))), np.log(rr), D)
            s = RG.summarise(sc, rows, B=500)
            res[cname][f"fixed_{tgt}"] = dict(r=rr, D=D, **{k: s[k] for k in ("sensitivity", "sens_ci", "fa_per_hour", "latency_median")})
        fw = []
        for r in recs:
            x = score_record(r["cond"][cname]["fw_alarms"], [tuple(v) for v in r["seizures"]], r["duration_s"])
            x["case"] = r["case"]; fw.append(x)
        from scoring import summarise as S0
        f = S0(fw)
        res[cname]["firmware_blackout"] = dict(sensitivity=f["sensitivity"], fa_per_hour=f["fa_per_hour"])
        print(cname, json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk in ('sensitivity', 'fa_per_hour')}) for k, v in res[cname].items()}), flush=True)
    res["fixed_params"] = {str(k): v for k, v in fixed.items()}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="results_hw")
    ap.add_argument("--jobs", type=int, default=2)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    jobs = list(discover(Path(a.data)))
    t0 = time.time()
    with Pool(a.jobs) as pool:
        recs = [r for r in pool.imap_unordered(one, jobs) if r is not None]
    recs.sort(key=lambda r: r["record"])
    print(f"{len(recs)} recordings processed in {time.time()-t0:.0f}s", flush=True)
    np.savez_compressed(out / "delta_series.npz",
                        **{f"{r['record']}__{c}": np.asarray(r['cond'][c]['delta'], np.float32) for r in recs for c in COND})
    res = evaluate(recs, out)
    res["recordings"] = len(recs)
    res["seizures"] = sum(len(r["seizures"]) for r in recs)
    (out / "hw_robustness.json").write_text(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main()
