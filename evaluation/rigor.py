"""
Rigor analyses for the baseline-ratio (BR) detectors on the primary channel.

  1. Subject grouping: chb21 is the same person as chb01 → one subject ("S01").
  2. Leave-one-subject-out CV (LOSO, 23 folds) and the original 2-fold CV.
  3. Nested signal selection: inside each training fold the signal
     (LL / DEV / FUSE) is chosen together with (r, D), so the final choice of
     DEV is not made on held-out data.
  4. Pooled and subject-macro sensitivity, FA/h over total and inter-ictal time,
     subject-level bootstrap CIs, Wilcoxon tests on subjects.
  5. Empirical null: each detector's alarm train is circularly shifted by a
     random offset inside every recording (alarm count and spacing preserved)
     and re-scored, 1000 times.
  6. Ablations (LOSO): baseline lag, window length, median vs mean, and an
     un-normalized absolute threshold on the deviation.
  7. Cold-start accounting: seizures starting before the BR warm-up ends.

usage: python rigor.py --results results [--channel FP1-FP2] [--perm 1000]
writes results/rigor_<channel>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scoring import MERGE_S, PRE_S, POST_S, score_record                 # noqa: E402
import personalize as P                                                  # noqa: E402

R_GRID = [1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0]
D_GRID = [2, 4, 6, 8, 10, 15, 20, 30]
TARGETS = [1.0, 0.5, 0.2]


def subject(case):
    return "chb01" if case == "chb21" else case


# ── score construction with configurable baseline ────────────────────────────
def baseline_score(y, win=300, lag=30, stat="median", log=True):
    import pandas as pd
    s = pd.Series(y)
    roll = s.rolling(win, min_periods=win // 2)
    bg = (roll.median() if stat == "median" else roll.mean()).shift(lag).to_numpy()
    if not log:
        return None
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.log(np.maximum(y, 1e-9) / np.maximum(bg, 1e-9))
    r[: win + lag] = np.nan
    return r


def series(res, rec, ch, n):
    z = np.load(res / "features" / f"{rec}_{ch}.npz")
    ll = P.per_second(z["ft"], z["ll"], n)
    dev = P.per_second(z["fw_t10"], z["fw_diff10"], n)
    return ll, dev


# ── fast alarm evaluation with cached running minima ─────────────────────────
class Cache:
    def __init__(self, rows, key):
        self.rows, self.key = rows, key
        self.m = {}

    def runmin(self, i, D):
        k = (i, D)
        if k not in self.m:
            self.m[k] = P.run_min(self.rows[i]["S"][self.key], D)
        return self.m[k]


def alarms_from_min(m, th):
    above = m >= th
    on = np.flatnonzero(above & ~np.concatenate([[False], above[:-1]])) + 1.0
    out = []
    for a in on:
        if not out or a - out[-1] >= MERGE_S:
            out.append(float(a))
    return out


def score_set(cache, idx, th, D):
    sc = []
    for i in idx:
        r = cache.rows[i]
        al = alarms_from_min(cache.runmin(i, D), th)
        s = score_record(al, [tuple(x) for x in r["seizures"]], r["duration_s"])
        s["subject"] = subject(r["case"]); s["alarms"] = al; s["i"] = i
        sc.append(s)
    return sc


def agg(sc):
    nsz = sum(s["n_sz"] for s in sc); ndet = sum(sum(s["detected"]) for s in sc)
    h = sum(s["hours"] for s in sc); fa = sum(s["n_fa"] for s in sc)
    return ndet / max(nsz, 1), fa / max(h, 1e-9)


def select(caches, idx, target, sigs):
    best = None
    for sig in sigs:
        c = caches[sig]
        for rr in R_GRID:
            for D in D_GRID:
                sens, fah = agg(score_set(c, idx, np.log(rr), D))
                if fah <= target and (best is None or sens > best[0] or (sens == best[0] and fah < best[1])):
                    best = (sens, fah, sig, rr, D)
    return best


def cv(caches, rows, folds, target, sigs):
    """folds: list of held-out index lists.  returns per-record scored list + choices."""
    allidx = list(range(len(rows)))
    held, choices = [], []
    for te in folds:
        tr = [i for i in allidx if i not in set(te)]
        b = select(caches, tr, target, sigs)
        choices.append(dict(sig=b[2], r=b[3], D=b[4], train_sens=b[0], train_fah=b[1],
                            held_out=sorted({subject(rows[i]["case"]) for i in te})))
        held += score_set(caches[b[2]], te, np.log(b[3]), b[4])
    return held, choices


# ── summaries ────────────────────────────────────────────────────────────────
def summarise(sc, rows, B=2000, seed=0):
    rng = np.random.default_rng(seed)
    subj = sorted({s["subject"] for s in sc})
    per = {u: dict(n_sz=0, n_det=0, n_fa=0, hours=0.0, ictal_h=0.0, lat=[]) for u in subj}
    for s in sc:
        p = per[s["subject"]]
        p["n_sz"] += s["n_sz"]; p["n_det"] += sum(s["detected"]); p["n_fa"] += s["n_fa"]; p["hours"] += s["hours"]
        p["lat"] += [l for l in s["latency"] if l == l]
        r = rows[s["i"]] if "i" in s else None
        if r is not None:
            p["ictal_h"] += sum(off - on for on, off in r["seizures"]) / 3600
    nsz = sum(p["n_sz"] for p in per.values()); ndet = sum(p["n_det"] for p in per.values())
    fa = sum(p["n_fa"] for p in per.values()); h = sum(p["hours"] for p in per.values())
    ih = h - sum(p["ictal_h"] for p in per.values())
    macro = [p["n_det"] / p["n_sz"] for p in per.values() if p["n_sz"]]
    lats = [l for p in per.values() for l in p["lat"]]
    a = np.array([[per[u]["n_det"], per[u]["n_sz"], per[u]["n_fa"], per[u]["hours"]] for u in subj], float)
    ix = rng.integers(0, len(subj), (B, len(subj)))
    bs = a[ix].sum(1)
    sens_b = bs[:, 0] / np.maximum(bs[:, 1], 1); fah_b = bs[:, 2] / bs[:, 3]
    mac_b = []
    for row in ix:
        v = [a[j, 0] / a[j, 1] for j in row if a[j, 1] > 0]
        mac_b.append(np.mean(v))
    return dict(seizures=int(nsz), detected=int(ndet), sensitivity=ndet / max(nsz, 1),
                sens_ci=[float(np.percentile(sens_b, 2.5)), float(np.percentile(sens_b, 97.5))],
                macro_sensitivity=float(np.mean(macro)),
                macro_ci=[float(np.percentile(mac_b, 2.5)), float(np.percentile(mac_b, 97.5))],
                false_alarms=int(fa), hours=h, fa_per_hour=fa / h, fa_per_hour_interictal=fa / ih,
                fah_ci=[float(np.percentile(fah_b, 2.5)), float(np.percentile(fah_b, 97.5))],
                latency_median=float(np.median(lats)) if lats else float("nan"),
                latency_iqr=[float(np.percentile(lats, 25)), float(np.percentile(lats, 75))] if lats else [float("nan")] * 2,
                subjects=len(subj),
                per_subject={u: dict(n_sz=per[u]["n_sz"], n_det=per[u]["n_det"], n_fa=per[u]["n_fa"], hours=per[u]["hours"]) for u in subj})


def null_test(sc, rows, n_perm, seed=1):
    """circular-shift empirical null for the sensitivity of a set of scored records."""
    rng = np.random.default_rng(seed)
    obs = sum(sum(s["detected"]) for s in sc)
    tot = sum(s["n_sz"] for s in sc)
    null = np.zeros(n_perm)
    for k in range(n_perm):
        det = 0
        for s in sc:
            r = rows[s["i"]]
            if not r["seizures"]:
                continue
            dur = r["duration_s"]
            al = np.asarray(s["alarms"], float)
            if len(al) == 0:
                continue
            sh = (al + rng.uniform(0, dur)) % dur
            for on, off in r["seizures"]:
                det += bool(np.any((sh >= on - PRE_S) & (sh <= off + POST_S)))
        null[k] = det
    return dict(observed=obs / tot, null_mean=float(null.mean() / tot), null_p95=float(np.percentile(null, 95) / tot),
                p=float((1 + np.sum(null >= obs)) / (1 + n_perm)))


def shipped_scored(rows, recs, det, kind):
    sc = []
    for i, r in enumerate(rows):
        al = recs[r["record"]][det][kind]
        s = score_record(al, [tuple(x) for x in r["seizures"]], r["duration_s"])
        s["subject"] = subject(r["case"]); s["alarms"] = al; s["i"] = i
        sc.append(s)
    return sc


def wilcoxon_subjects(a, b):
    from scipy.stats import wilcoxon
    u = sorted(set(a["per_subject"]) & set(b["per_subject"]))
    x = np.array([a["per_subject"][k]["n_det"] / a["per_subject"][k]["n_sz"] for k in u if a["per_subject"][k]["n_sz"]])
    y = np.array([b["per_subject"][k]["n_det"] / b["per_subject"][k]["n_sz"] for k in u if b["per_subject"][k]["n_sz"]])
    d = x - y
    p = float(wilcoxon(x, y).pvalue) if np.any(d != 0) else 1.0
    return dict(n=int(len(x)), better=int((d > 0).sum()), worse=int((d < 0).sum()), ties=int((d == 0).sum()), p=p)


def main():
    global R_GRID
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--channel", default="FP1-FP2")
    ap.add_argument("--perm", type=int, default=1000)
    a = ap.parse_args()
    res = Path(a.results); ch = a.channel
    allrec = [json.loads(l) for l in (res / "records.jsonl").read_text().splitlines() if l.strip()]
    recs = {r["record"]: r for r in allrec if r["channel"] == ch and not r.get("missing")}
    rows = sorted(recs.values(), key=lambda r: r["record"])
    for r in rows:
        n = int(np.floor(r["duration_s"]))
        r["ll1"], r["dev1"] = series(res, r["record"], ch, n)
        sl, sd = baseline_score(r["ll1"]), baseline_score(r["dev1"])
        r["S"] = {"LL": sl, "DEV": sd, "FUSE": 0.5 * (sl + sd)}
    caches = {k: Cache(rows, k) for k in ("LL", "DEV", "FUSE")}
    subjects = sorted({subject(r["case"]) for r in rows})
    loso = [[i for i, r in enumerate(rows) if subject(r["case"]) == u] for u in subjects]
    two = [[i for i, r in enumerate(rows) if P.fold_of(r["case"]) == f] for f in (0, 1)]
    out = dict(channel=ch, subjects=len(subjects), recordings=len(rows),
               seizures=sum(len(r["seizures"]) for r in rows), hours=sum(r["duration_s"] for r in rows) / 3600,
               cold_start_seizures=sum(1 for r in rows for on, off in r["seizures"] if on < 335),
               grid=dict(r=R_GRID, D=D_GRID), methods={}, choices={}, nulls={}, tests={}, ablation={})
    # shipped detectors
    ship = {}
    for name, det, kind in (("py_blackout", "py", "seizure_alarms"), ("py_any", "py", "any_alarms"),
                            ("fw_blackout", "fw", "seizure_alarms")):
        sc = shipped_scored(rows, recs, det, kind)
        ship[name] = sc
        out["methods"][name] = summarise(sc, rows)
        out["nulls"][name] = null_test(sc, rows, a.perm)
    # BR detectors: LOSO and 2-fold, per-signal and nested
    held = {}
    for scheme, folds in (("loso", loso), ("2fold", two)):
        for tgt in TARGETS:
            for sigs, lab in ((["DEV"], "DEV"), (["LL"], "LL"), (["FUSE"], "FUSE"), (["LL", "DEV", "FUSE"], "NESTED")):
                if scheme == "2fold" and lab == "FUSE":
                    continue
                sc, ch_ = cv(caches, rows, folds, tgt, sigs)
                key = f"{scheme}_{lab}_{tgt}"
                held[key] = sc
                out["methods"][key] = summarise(sc, rows)
                out["choices"][key] = ch_
                print(key, f"{100*out['methods'][key]['sensitivity']:.1f}% @ {out['methods'][key]['fa_per_hour']:.2f}", flush=True)
    for key in ("loso_DEV_1.0", "loso_DEV_0.5", "loso_NESTED_1.0", "loso_NESTED_0.5", "loso_LL_1.0"):
        out["nulls"][key] = null_test(held[key], rows, a.perm)
    M = out["methods"]
    out["tests"]["loso_DEV_0.5_vs_py_blackout"] = wilcoxon_subjects(M["loso_DEV_0.5"], M["py_blackout"])
    out["tests"]["loso_DEV_1.0_vs_py_any"] = wilcoxon_subjects(M["loso_DEV_1.0"], M["py_any"])
    out["tests"]["loso_DEV_1.0_vs_LL_1.0"] = wilcoxon_subjects(M["loso_DEV_1.0"], M["loso_LL_1.0"])
    out["tests"]["loso_NESTED_0.5_vs_py_blackout"] = wilcoxon_subjects(M["loso_NESTED_0.5"], M["py_blackout"])
    # excluding cold-start seizures
    for key in ("loso_DEV_1.0", "loso_DEV_0.5"):
        sc = held[key]; nsz = ndet = 0
        for s in sc:
            r = rows[s["i"]]
            for (on, off), d in zip(r["seizures"], s["detected"]):
                if on >= 335:
                    nsz += 1; ndet += d
        out["methods"][key]["sensitivity_excl_coldstart"] = ndet / nsz
        out["methods"][key]["seizures_excl_coldstart"] = nsz
    # ablations (LOSO, DEV, targets 1.0 and 0.5)
    variants = {"lag0": dict(lag=0), "lag10": dict(lag=10), "lag60": dict(lag=60),
                "win60": dict(win=60), "win120": dict(win=120), "win600": dict(win=600),
                "mean": dict(stat="mean")}
    for vname, kw in variants.items():
        for r in rows:
            r["S"]["ABL"] = baseline_score(r["dev1"], **kw)
        c = {"ABL": Cache(rows, "ABL")}
        out["ablation"][vname] = {}
        for tgt in (1.0, 0.5):
            sc, chs = cv(c, rows, loso, tgt, ["ABL"])
            s = summarise(sc, rows, B=200)
            out["ablation"][vname][str(tgt)] = {k: s[k] for k in ("sensitivity", "macro_sensitivity", "fa_per_hour", "latency_median")}
            print("ablation", vname, tgt, f"{100*s['sensitivity']:.1f}% @ {s['fa_per_hour']:.2f}", flush=True)
    # un-normalized absolute threshold on per-second deviation (ADC units)
    for r in rows:
        x = r["dev1"].astype(float).copy(); x[:330] = np.nan
        r["S"]["ABS"] = np.log(np.maximum(x, 1e-9))
    c = {"ABS": Cache(rows, "ABS")}
    saved = R_GRID
    R_GRID = [float(v) for v in np.round(np.geomspace(5, 400, 24), 2)]   # absolute ADC thresholds
    out["ablation"]["absolute"] = {}
    for tgt in (1.0, 0.5):
        sc, chs = cv(c, rows, loso, tgt, ["ABS"])
        s = summarise(sc, rows, B=200)
        out["ablation"]["absolute"][str(tgt)] = {k: s[k] for k in ("sensitivity", "macro_sensitivity", "fa_per_hour", "latency_median")}
        print("ablation absolute", tgt, f"{100*s['sensitivity']:.1f}% @ {s['fa_per_hour']:.2f}", flush=True)
    R_GRID = saved
    (res / f"rigor_{ch}.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
