"""
Paper-level analysis on top of run_eval / personalize outputs:
  • shipped detectors and ratio detectors on every channel, with chance levels
  • patient-level bootstrap 95% CIs for sensitivity and FA/h
  • in-sample operating grids for LL-R and DEV-R (for the trade-off figure)
  • per-patient sensitivity of the proposed detector

usage: python final_analysis.py --results results [--boot 2000]
writes results/final.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scoring import score_record, summarise, PRE_S, POST_S        # noqa: E402
import personalize as P                                           # noqa: E402

CHANNELS = ["FP1-FP2", "FP1-F7", "FP2-F8"]


def per_case_counts(scored):
    pc = {}
    for s in scored:
        c = pc.setdefault(s["case"], dict(n_sz=0, n_det=0, n_fa=0, hours=0.0, lat=[]))
        c["n_sz"] += s["n_sz"]; c["n_det"] += sum(s["detected"]); c["n_fa"] += s["n_fa"]; c["hours"] += s["hours"]
        c["lat"] += [l for l in s["latency"] if l == l]
    return pc


def boot_ci(pc, B, rng):
    cases = list(pc)
    det = np.array([pc[c]["n_det"] for c in cases]); sz = np.array([pc[c]["n_sz"] for c in cases])
    fa = np.array([pc[c]["n_fa"] for c in cases]); hr = np.array([pc[c]["hours"] for c in cases])
    idx = rng.integers(0, len(cases), size=(B, len(cases)))
    sens = det[idx].sum(1) / np.maximum(sz[idx].sum(1), 1)
    fah = fa[idx].sum(1) / hr[idx].sum(1)
    return [float(np.percentile(sens, 2.5)), float(np.percentile(sens, 97.5))], \
           [float(np.percentile(fah, 2.5)), float(np.percentile(fah, 97.5))]


def chance(rows, fa_per_hour):
    lam = fa_per_hour / 3600.0
    p = [1 - np.exp(-lam * (off - on + PRE_S + POST_S)) for r in rows for on, off in r["seizures"]]
    return float(np.mean(p)) if p else float("nan")


def pack(scored, rows, B, rng, extra=None):
    s = summarise(scored)
    pc = per_case_counts(scored)
    ci_s, ci_f = boot_ci(pc, B, rng)
    d = {k: v for k, v in s.items() if k != "per_case"}
    d.update(sens_ci=ci_s, fah_ci=ci_f, chance=chance(rows, s["fa_per_hour"]),
             per_case={c: dict(n_sz=v["n_sz"], n_det=v["n_det"], n_fa=v["n_fa"], hours=v["hours"]) for c, v in pc.items()})
    if extra:
        d.update(extra)
    return d


def shipped(rows, det, kind):
    out = []
    for r in rows:
        s = score_record(r[det][kind], [tuple(x) for x in r["seizures"]], r["duration_s"])
        s["case"] = r["case"]; out.append(s)
    return out


def ratio_cv_scored(rows, sig, target):
    test, chosen = [], []
    for f in (0, 1):
        tr = [r for r in rows if P.fold_of(r["case"]) != f]
        te = [r for r in rows if P.fold_of(r["case"]) == f]
        best = None
        for rr in P.R_GRID:
            for D in P.D_GRID:
                s = P.evaluate(tr, sig, lambda r, rr=rr: np.log(rr), D)
                if s["fa_per_hour"] <= target and (best is None or s["sensitivity"] > best[0]):
                    best = (s["sensitivity"], rr, D)
        chosen.append((f, best[1], best[2]))
        for r in te:
            al = P.alarms(r["S"][sig], np.log(best[1]), best[2])
            s = score_record(al, [tuple(x) for x in r["seizures"]], r["duration_s"])
            s["case"] = r["case"]; test.append(s)
    return test, chosen


def grid(rows, sig):
    g = []
    for rr in P.R_GRID:
        for D in P.D_GRID:
            s = P.evaluate(rows, sig, lambda r, rr=rr: np.log(rr), D)
            g.append(dict(r=rr, D=D, sensitivity=s["sensitivity"], fa_per_hour=s["fa_per_hour"]))
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--boot", type=int, default=2000)
    a = ap.parse_args()
    res = Path(a.results)
    rng = np.random.default_rng(42)
    all_rows = [json.loads(l) for l in (res / "records.jsonl").read_text().splitlines() if l.strip()]
    out = {}
    for ch in CHANNELS:
        rows = P.load_all(res, ch)
        if not rows:
            continue
        rec = {r["record"]: r for r in all_rows if r["channel"] == ch and not r.get("missing")}
        for r in rows:                                  # attach shipped-detector alarms
            r["py"], r["fw"] = rec[r["record"]]["py"], rec[r["record"]]["fw"]
        o = dict(n_patients=len({r["case"] for r in rows}), n_records=len(rows),
                 n_seizures=sum(len(r["seizures"]) for r in rows),
                 hours=sum(r["duration_s"] for r in rows) / 3600, methods={})
        o["methods"]["py_blackout"] = pack(shipped(rows, "py", "seizure_alarms"), rows, a.boot, rng)
        o["methods"]["py_any"] = pack(shipped(rows, "py", "any_alarms"), rows, a.boot, rng)
        o["methods"]["fw_blackout"] = pack(shipped(rows, "fw", "seizure_alarms"), rows, a.boot, rng)
        o["methods"]["fw_any"] = pack(shipped(rows, "fw", "any_alarms"), rows, a.boot, rng)
        for sig in ("LL", "DEV", "FUSE"):
            for tgt in (1.0, 0.5, 0.2):
                sc, chosen = ratio_cv_scored(rows, sig, tgt)
                o["methods"][f"{sig}_{tgt}"] = pack(sc, rows, a.boot, rng, dict(chosen=chosen))
        if ch == "FP1-FP2":
            o["grid"] = {sig: grid(rows, sig) for sig in ("LL", "DEV")}
        out[ch] = o
        m = o["methods"]
        print(ch, o["n_seizures"], "sz", round(o["hours"], 1), "h |",
              " ".join(f"{k}:{100*v['sensitivity']:.1f}%@{v['fa_per_hour']:.2f}" for k, v in m.items()))
    (res / "final.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
