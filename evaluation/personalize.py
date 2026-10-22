"""
Scale-free ratio detectors and caregiver-calibrated personalization.

All detectors run on 1-Hz summaries of two signals Vera already computes:
  LL  – the analyzer's line-length (mean per second)
  DEV – the firmware's |x − EMA baseline| deviation (mean per second)
Each is divided by its own lagged running median (window [t−330, t−30] s), so
scores are dimensionless and independent of electrode impedance / gain.

  S_LL  = log R_LL          S_DEV = log R_DEV          S_FUSE = (S_LL + S_DEV)/2

Alarm: S ≥ θ for D consecutive seconds (alarms < 90 s apart merged).

Two ways of setting θ:
  • population   – θ = log r, (r, D) chosen by patient-wise 2-fold CV
  • personal (caregiver-calibrated) – the caregiver marks ONE seizure in the app.
    From that seizure alone the device takes p = the largest θ that would have
    raised an alarm (max over the seizure of the D-s running minimum of S),
    and sets θ = max(α·p, log f).  (α, f, D) are chosen by patient-wise 2-fold CV
    on *other* patients; the patient's own data contribute only the one
    calibration seizure, and every recording from that calibration file is
    excluded from evaluation.  The calibration seizure is the patient's first
    (chronological) seizure.

usage: python personalize.py --results results --channel FP1-FP2
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scoring import MERGE_S, PRE_S, POST_S, score_record, summarise   # noqa: E402

BG_WIN, BG_LAG = 300, 30
DEAD = BG_WIN + BG_LAG


# ── 1-Hz scores ──────────────────────────────────────────────────────────────
def per_second(t, x, n):
    sec = np.clip(t.astype(np.int64), 0, n - 1)
    s = np.bincount(sec, weights=x.astype(np.float64), minlength=n)
    c = np.bincount(sec, minlength=n)
    y = np.where(c > 0, s / np.maximum(c, 1), np.nan)
    idx = np.where(np.isfinite(y), np.arange(n), 0)
    np.maximum.accumulate(idx, out=idx)
    return y[idx]


def log_ratio(y):
    import pandas as pd
    bg = pd.Series(y).rolling(BG_WIN, min_periods=BG_WIN // 2).median().shift(BG_LAG).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.log(np.maximum(y, 1e-9) / np.maximum(bg, 1e-9))
    r[:DEAD] = np.nan
    return r


def scores_for(feat_path, duration_s):
    z = np.load(feat_path)
    n = int(np.floor(duration_s))
    ll = per_second(z["ft"], z["ll"], n)
    dev = per_second(z["fw_t10"], z["fw_diff10"], n)
    s_ll, s_dev = log_ratio(ll), log_ratio(dev)
    return {"LL": s_ll, "DEV": s_dev, "FUSE": 0.5 * (s_ll + s_dev)}


# ── alarms ───────────────────────────────────────────────────────────────────
def run_min(S, D):
    """running minimum over the last D seconds (NaN → -inf)."""
    x = np.nan_to_num(S, nan=-np.inf)
    if D <= 1:
        return x
    from numpy.lib.stride_tricks import sliding_window_view
    pad = np.concatenate([np.full(D - 1, -np.inf), x])
    return sliding_window_view(pad, D).min(axis=1)


def alarms(S, theta, D, _cache={}):
    m = run_min(S, D)
    above = m >= theta
    onsets = np.where(above & ~np.concatenate([[False], above[:-1]]))[0] + 1.0
    out = []
    for a in onsets:
        if not out or a - out[-1] >= MERGE_S:
            out.append(float(a))
    return out


# ── data assembly ────────────────────────────────────────────────────────────
def load_all(res: Path, channel: str):
    rows = [json.loads(l) for l in (res / "records.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r["channel"] == channel and not r.get("missing")]
    rows.sort(key=lambda r: r["record"])
    for r in rows:
        r["S"] = scores_for(res / "features" / f"{r['record']}_{channel}.npz", r["duration_s"])
    return rows


def fold_of(case):
    return 1 if case == "chb21" else int(case[3:]) % 2


def evaluate(rows, sig, theta_fn, D):
    """theta_fn(row) -> theta (or None to skip row)."""
    sc = []
    for r in rows:
        th = theta_fn(r)
        if th is None:
            continue
        al = alarms(r["S"][sig], th, D)
        s = score_record(al, [tuple(x) for x in r["seizures"]], r["duration_s"])
        s["case"] = r["case"]; sc.append(s)
    return summarise(sc) if sc else None


# ── population thresholds (patient-wise 2-fold CV) ───────────────────────────
R_GRID = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0]
D_GRID = [2, 4, 6, 8, 10, 15, 20]


def population_cv(rows, sig, target):
    test_scored, chosen = [], []
    for f in (0, 1):
        tr = [r for r in rows if fold_of(r["case"]) != f]
        te = [r for r in rows if fold_of(r["case"]) == f]
        best = None
        for rr in R_GRID:
            for D in D_GRID:
                s = evaluate(tr, sig, lambda r, rr=rr: np.log(rr), D)
                if s["fa_per_hour"] <= target and (best is None or s["sensitivity"] > best[0]):
                    best = (s["sensitivity"], rr, D)
        if best is None:
            continue
        chosen.append((f, best[1], best[2]))
        for r in te:
            al = alarms(r["S"][sig], np.log(best[1]), best[2])
            s = score_record(al, [tuple(x) for x in r["seizures"]], r["duration_s"])
            s["case"] = r["case"]; test_scored.append(s)
    return summarise(test_scored), chosen


# ── personalization ──────────────────────────────────────────────────────────
A_GRID = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
F_GRID = [1.25, 1.5, 2.0, 2.5, 3.0]
DP_GRID = [2, 4, 6, 8, 10, 15]


def calibration_split(rows):
    """per patient: first seizure (chronological) → (calib_row, seizure); eval rows exclude that file."""
    by = {}
    for r in rows:
        by.setdefault(r["case"], []).append(r)
    plan = {}
    for c, rs in by.items():
        rs.sort(key=lambda r: r["record"])
        cal = next(((r, sz) for r in rs for sz in sorted(r["seizures"]) if sz[0] > DEAD + 5), None)
        if cal is None:
            continue
        ev = [r for r in rs if r["record"] != cal[0]["record"]]
        if not any(r["seizures"] for r in ev):
            continue
        plan[c] = (cal, ev)
    return plan


def peak_on(S, sz, D):
    on, off = int(sz[0]), int(sz[1])
    m = run_min(S, D)[on: off + int(POST_S) + 1]      # what the alarm logic could have seen
    m = m[np.isfinite(m)]
    return float(m.max()) if len(m) else -np.inf


def personal_eval(plan, cases, sig, a, f, D):
    sc = []
    for c in cases:
        (crow, csz), ev = plan[c]
        p = peak_on(crow["S"][sig], csz, D)
        th = max(a * p, np.log(f))
        for r in ev:
            al = alarms(r["S"][sig], th, D)
            s = score_record(al, [tuple(x) for x in r["seizures"]], r["duration_s"])
            s["case"] = r["case"]; sc.append(s)
    return summarise(sc)


def personal_cv(plan, sig, target):
    cases = sorted(plan)
    test, chosen = [], []
    for fo in (0, 1):
        tr = [c for c in cases if fold_of(c) != fo]
        te = [c for c in cases if fold_of(c) == fo]
        best = None
        for a in A_GRID:
            for f in F_GRID:
                for D in DP_GRID:
                    s = personal_eval(plan, tr, sig, a, f, D)
                    if s["fa_per_hour"] <= target and (best is None or s["sensitivity"] > best[0]):
                        best = (s["sensitivity"], a, f, D)
        if best is None:
            continue
        chosen.append((fo, best[1], best[2], best[3]))
        for c in te:
            (crow, csz), ev = plan[c]
            p = peak_on(crow["S"][sig], csz, best[3])
            th = max(best[1] * p, np.log(best[2]))
            for r in ev:
                al = alarms(r["S"][sig], th, best[3])
                s = score_record(al, [tuple(x) for x in r["seizures"]], r["duration_s"])
                s["case"] = r["case"]; test.append(s)
    return summarise(test), chosen


# ── wearer-baseline self-calibration (no seizure labels) ─────────────────────
# The device wears in for its first recordings (here: the patient's first two,
# chronologically — unlabeled, so any seizures in them are simply part of the
# data).  For each persistence D it picks the lowest θ whose alarm rate on that
# wear-in data stays ≤ q, then never adapts again.  (q, D) are chosen by
# patient-wise 2-fold CV; the wear-in recordings are excluded from evaluation.
TH_GRID = np.round(np.arange(0.05, 3.01, 0.05), 3)
Q_GRID = [0.25, 0.5, 1.0, 2.0]
DS_GRID = [4, 8, 10, 15, 20]
N_WEAR = 2


def wear_split(rows):
    by = {}
    for r in rows:
        by.setdefault(r["case"], []).append(r)
    plan = {}
    for c, rs in by.items():
        rs.sort(key=lambda r: r["record"])
        if len(rs) <= N_WEAR:
            continue
        cal, ev = rs[:N_WEAR], rs[N_WEAR:]
        if any(r["seizures"] for r in ev):
            plan[c] = (cal, ev)
    return plan


def self_theta(cal, sig, D, q):
    hours = sum(r["duration_s"] for r in cal) / 3600
    for th in TH_GRID:
        n = sum(len(alarms(r["S"][sig], th, D)) for r in cal)
        if n / hours <= q:
            return th
    return TH_GRID[-1]


def self_eval(plan, cases, sig, q, D):
    sc = []
    for c in cases:
        cal, ev = plan[c]
        th = self_theta(cal, sig, D, q)
        for r in ev:
            al = alarms(r["S"][sig], th, D)
            s = score_record(al, [tuple(x) for x in r["seizures"]], r["duration_s"])
            s["case"] = r["case"]; sc.append(s)
    return summarise(sc)


def self_cv(plan, sig, target):
    cases = sorted(plan); test, chosen = [], []
    for fo in (0, 1):
        tr = [c for c in cases if fold_of(c) != fo]; te = [c for c in cases if fold_of(c) == fo]
        best = None
        for q in Q_GRID:
            for D in DS_GRID:
                s = self_eval(plan, tr, sig, q, D)
                if s["fa_per_hour"] <= target and (best is None or s["sensitivity"] > best[0]):
                    best = (s["sensitivity"], q, D)
        if best is None:
            continue
        chosen.append((fo, best[1], best[2]))
        s = self_eval(plan, te, sig, best[1], best[2])
        for c, v in s["per_case"].items():
            pass
        for c in te:
            cal, ev = plan[c]
            th = self_theta(cal, sig, best[2], best[1])
            for r in ev:
                al = alarms(r["S"][sig], th, best[2])
                x = score_record(al, [tuple(y) for y in r["seizures"]], r["duration_s"])
                x["case"] = r["case"]; test.append(x)
    return summarise(test), chosen


def strip(s):
    return {k: v for k, v in s.items() if k != "per_case"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--channel", default="FP1-FP2")
    a = ap.parse_args()
    res = Path(a.results)
    rows = load_all(res, a.channel)
    out = dict(channel=a.channel, full={}, tap={}, wear={})
    md = [f"# Ratio detectors and personalization — {a.channel}\n"]

    # A. population ratio detectors on the full set
    md += ["## A. Population thresholds, all recordings (patient-wise 2-fold CV)",
           "| Signal | FA/h target | Params (fold0; fold1) | Detected | Sens. | FA/h | Latency (s) |", "|---|---|---|---|---|---|---|"]
    for tgt in (1.0, 0.5, 0.2):
        for sig in ("LL", "DEV", "FUSE"):
            s, ch = population_cv(rows, sig, tgt)
            out["full"][f"{sig}_{tgt}"] = dict(chosen=ch, **strip(s),
                per_case={c: dict(n_sz=v["n_sz"], n_det=v["n_det"], n_fa=v["n_fa"], hours=v["hours"]) for c, v in s["per_case"].items()})
            md.append(f"| {sig} | ≤{tgt} | " + "; ".join(f"r={r},D={d}" for _, r, d in ch) +
                      f" | {s['detected']}/{s['seizures']} | {100*s['sensitivity']:.1f}% | {s['fa_per_hour']:.2f} | {s['latency_median']:.1f} |")

    # B. caregiver-tap calibration vs population, same evaluation set
    plan = calibration_split(rows)
    ev_rows = [r for c in sorted(plan) for r in plan[c][1]]
    out["tap"]["eval"] = dict(patients=len(plan), seizures=sum(len(r["seizures"]) for r in ev_rows),
                              hours=sum(r["duration_s"] for r in ev_rows) / 3600)
    md += ["", f"## B. One caregiver-marked seizure (eval set: {out['tap']['eval']['patients']} patients, "
           f"{out['tap']['eval']['seizures']} seizures, {out['tap']['eval']['hours']:.1f} h)",
           "| Method | FA/h target | Detected | Sens. | FA/h |", "|---|---|---|---|---|"]
    for tgt in (1.0, 0.5):
        for sig in ("DEV", "FUSE"):
            s0, _ = population_cv(ev_rows, sig, tgt); s1, ch = personal_cv(plan, sig, tgt)
            out["tap"][f"{sig}_{tgt}"] = dict(population=strip(s0), personal=dict(chosen=ch, **strip(s1)))
            md.append(f"| population {sig} | ≤{tgt} | {s0['detected']}/{s0['seizures']} | {100*s0['sensitivity']:.1f}% | {s0['fa_per_hour']:.2f} |")
            md.append(f"| caregiver-tap {sig} | ≤{tgt} | {s1['detected']}/{s1['seizures']} | {100*s1['sensitivity']:.1f}% | {s1['fa_per_hour']:.2f} |")

    # C. wearer-baseline self-calibration vs population, same evaluation set
    wplan = wear_split(rows)
    wev = [r for c in sorted(wplan) for r in wplan[c][1]]
    out["wear"]["eval"] = dict(patients=len(wplan), seizures=sum(len(r["seizures"]) for r in wev),
                               hours=sum(r["duration_s"] for r in wev) / 3600,
                               wear_hours=sum(r["duration_s"] for c in wplan for r in wplan[c][0]) / 3600)
    md += ["", f"## C. Wearer-baseline self-calibration (eval set: {out['wear']['eval']['patients']} patients, "
           f"{out['wear']['eval']['seizures']} seizures, {out['wear']['eval']['hours']:.1f} h; first {N_WEAR} recordings = wear-in)",
           "| Method | FA/h target | Params | Detected | Sens. | FA/h | Latency (s) |", "|---|---|---|---|---|---|---|"]
    for tgt in (1.0, 0.5, 0.2):
        for sig in ("DEV", "FUSE"):
            s0, c0 = population_cv(wev, sig, tgt); s1, c1 = self_cv(wplan, sig, tgt)
            out["wear"][f"{sig}_{tgt}"] = dict(population=dict(chosen=c0, **strip(s0)), self=dict(chosen=c1, **strip(s1)))
            md.append(f"| population {sig} | ≤{tgt} | " + "; ".join(f"r={r},D={d}" for _, r, d in c0) +
                      f" | {s0['detected']}/{s0['seizures']} | {100*s0['sensitivity']:.1f}% | {s0['fa_per_hour']:.2f} | {s0['latency_median']:.1f} |")
            md.append(f"| self-calibrated {sig} | ≤{tgt} | " + "; ".join(f"q={q},D={d}" for _, q, d in c1) +
                      f" | {s1['detected']}/{s1['seizures']} | {100*s1['sensitivity']:.1f}% | {s1['fa_per_hour']:.2f} | {s1['latency_median']:.1f} |")

    (res / "tables").mkdir(exist_ok=True)
    (res / "tables" / f"personal_{a.channel}.md").write_text("\n".join(md) + "\n")
    (res / f"personal_{a.channel}.json").write_text(json.dumps(out, indent=2, default=float))
    print("\n".join(md))


if __name__ == "__main__":
    main()
