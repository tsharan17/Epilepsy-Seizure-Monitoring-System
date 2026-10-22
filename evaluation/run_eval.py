"""
Replay CHB-MIT through both Vera detectors and store per-record results.

usage:
  python run_eval.py --data ../data/chbmit --monitor ../seizure_monitor.py \
                     --out results/records.jsonl [--channels FP1-F7 FP2-F8] [--jobs 2]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chbmit import discover, load_record, to_device_adc          # noqa: E402
from detectors import (load_monitor_module, run_firmware_detector,  # noqa: E402
                       run_python_detector)
from scoring import alarm_times                                    # noqa: E402

_MOD = None
_ARGS = None


def _init(monitor_path, args):
    global _MOD, _ARGS
    _MOD = load_monitor_module(Path(monitor_path))
    _ARGS = args


def _state_occupancy(states):
    s = np.asarray(states)
    return [float(np.mean(s == k)) if len(s) else 0.0 for k in range(4)]


def process(job):
    case, name, seizures, data_dir = job
    t0 = time.time()
    rec = load_record(Path(data_dir), case, name, seizures)
    out = []
    for ch in _ARGS["channels"]:
        if ch not in rec.uv:
            out.append(dict(case=case, record=name, channel=ch, missing=True,
                            seizures=seizures, duration_s=rec.duration_s))
            continue
        adc = to_device_adc(rec.uv[ch], rec.fs, gain=_ARGS["gain"], band=_ARGS["band"])
        clip_frac = float(np.mean((adc == 0) | (adc == 4095)))
        ncal, t_fw, st_fw, trace = run_firmware_detector(adc)
        t_py, st_py, n_art, feats, thr = run_python_detector(_MOD, adc[ncal:], trace)
        t_py = t_py + ncal / 200.0
        feats[:, 0] += ncal / 200.0; thr[:, 0] += ncal / 200.0
        # per-tick feature trace (all analysis ticks, incl. artifact-rejected)
        fdir = Path(_ARGS["feat_dir"]); fdir.mkdir(parents=True, exist_ok=True)
        d = trace[1].astype(np.float32); m = len(d) // 20 * 20     # fw diff @10 Hz
        np.savez_compressed(fdir / f"{name}_{ch}.npz",
                            t=t_py.astype(np.float32), state=st_py,
                            ft=feats[:, 0], ll=feats[:, 1],
                            dar=feats[:, 2], hfe=feats[:, 3], thr=thr,
                            fw_t10=t_fw[:m:20].astype(np.float32),
                            fw_state=st_fw[:m:20],
                            fw_diff10=d[:m].reshape(-1, 20).mean(1))
        art_ceiling = _MOD.Config().artifact_ll_ceiling
        ict = np.zeros(len(feats), bool)
        for on, off in seizures:
            ict |= (feats[:, 0] >= on) & (feats[:, 0] <= off)
        art = feats[:, 1] > art_ceiling
        art_stats = dict(ictal_ticks=int(ict.sum()), ictal_artifact_ticks=int((ict & art).sum()),
                         interictal_ticks=int((~ict).sum()), interictal_artifact_ticks=int((~ict & art).sum()))
        out.append(dict(
            case=case, record=name, channel=ch, missing=False,
            seizures=seizures, duration_s=len(adc) / 200.0,
            adc_clip_frac=clip_frac,
            adc_std=float(np.std(adc)),
            fw=dict(seizure_alarms=alarm_times(t_fw, st_fw, "seizure"),
                    any_alarms=alarm_times(t_fw, st_fw, "any"),
                    occupancy=_state_occupancy(st_fw)),
            py=dict(seizure_alarms=alarm_times(t_py, st_py, "seizure"),
                    any_alarms=alarm_times(t_py, st_py, "any"),
                    occupancy=_state_occupancy(st_py),
                    artifact_epochs=int(n_art), ticks=int(len(st_py)), **art_stats),
            secs=round(time.time() - t0, 1)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--monitor", required=True)
    ap.add_argument("--out", default="results/records.jsonl")
    ap.add_argument("--channels", nargs="+", default=["FP1-FP2", "FP1-F7", "FP2-F8"])
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--gain", type=float, default=1000.0, help="front-end gain (V/V)")
    ap.add_argument("--band", default="0.5,40", help="front-end pass-band 'lo,hi' in Hz, or 'none'")
    a = ap.parse_args()

    jobs = list(discover(Path(a.data)))
    out_path = Path(a.out); out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            r = json.loads(line); done.add(r["record"])
    jobs = [j for j in jobs if j[1] not in done]
    if a.limit:
        jobs = jobs[: a.limit]
    print(f"{len(jobs)} records to process ({len(done)} already done)", flush=True)
    args = dict(channels=[c.upper() for c in a.channels],
                feat_dir=str(out_path.parent / "features"), gain=a.gain,
                band=None if a.band.lower() == "none" else tuple(float(v) for v in a.band.split(",")))
    with Pool(a.jobs, initializer=_init, initargs=(a.monitor, args)) as pool, \
            open(out_path, "a") as fh:
        for i, res in enumerate(pool.imap_unordered(process, jobs), 1):
            for r in res:
                fh.write(json.dumps(r) + "\n")
            fh.flush()
            r0 = res[0]
            print(f"[{i}/{len(jobs)}] {r0['record']}  {r0.get('secs', '-')}s", flush=True)


if __name__ == "__main__":
    main()
