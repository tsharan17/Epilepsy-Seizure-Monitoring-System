"""
Embedded-friendly extensions of DEV-BR, all evaluated with leave-one-subject-out
selection (23 subjects; parameters and decision rule chosen on the 22 training
subjects only, by maximizing pooled sensitivity subject to an FA/h target).

  BASE   δ ≥ r·β for D consecutive seconds                         (DEV-BR)
  KOFN   δ ≥ r·β in at least ⌈q·n⌉ of the last n seconds            (k-of-n persistence)
  DUAL   rule A (high r, short D)  OR  rule B (low r, long D)        (dual time-scale)
  CONT   any of the above, with the baseline carried over from the preceding
         recording when the two are contiguous (gap ≤ 10 s), i.e. the device
         is assumed worn continuously rather than restarted for every file.

Speed: every (record, rule, parameters) combination is scored once; LOSO
selection is then pure summation.

usage: python variants.py --results results --summaries <dir with chbXX-summary.txt>
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scoring import score_record, MERGE_S                             # noqa: E402
import personalize as P                                               # noqa: E402
import rigor as RG                                                    # noqa: E402

WIN, LAG = 300, 30
R_BASE = [1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0]
D_BASE = [2, 4, 6, 8, 10, 15, 20, 30]


def file_times(summ_dir):
    """record -> (start_s, end_s) on a continuous clock (handles midnight roll-over per case)."""
    out = {}
    for p in sorted(Path(summ_dir).glob("chb*-summary.txt")):
        txt = p.read_text(errors="replace")
        prev_end, day = None, 0
        for b in re.split(r"File Name:\s*", txt)[1:]:
            name = b.split()[0].replace(".edf", "")
            ms = re.search(r"File Start Time:\s*(\d+):(\d+):(\d+)", b)
            me = re.search(r"File End Time:\s*(\d+):(\d+):(\d+)", b)
            if not ms or not me:
                continue
            s = int(ms[1]) * 3600 + int(ms[2]) * 60 + int(ms[3]) + day * 86400
            if prev_end is not None and s < prev_end - 3600:
                day += 1; s += 86400
            e = int(me[1]) * 3600 + int(me[2]) * 60 + int(me[3]) + day * 86400
            if e < s:
                e += 86400
            out[name] = (s, e); prev_end = e
    return out


def baseline_lr(delta, prefix=None):
    x = delta if prefix is None else np.concatenate([prefix, delta])
    bg = pd.Series(x).rolling(WIN, min_periods=WIN // 2).median().shift(LAG).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.log(np.maximum(x, 1e-9) / np.maximum(bg, 1e-9))
    if prefix is None:
        r[:WIN + LAG] = np.nan
    else:
        r[:WIN + LAG] = np.nan          # still need a full window, counted on the joined stream
        r = r[len(prefix):]
    return r


def onsets(mask):
    on = np.flatnonzero(mask & ~np.concatenate([[False], mask[:-1]])) + 1.0
    out = []
    for a in on:
        if not out or a - out[-1] >= MERGE_S:
            out.append(float(a))
    return out


def score(al, r):
    s = score_record(al, [tuple(x) for x in r["seizures"]], r["duration_s"])
    return np.array(s["detected"], bool), s["n_fa"], s["latency"]


def build_masks(S):
    """dict (r, D) -> boolean trigger mask (consecutive persistence)."""
    x = np.nan_to_num(S, nan=-np.inf)
    out = {}
    for D in D_BASE:
        m = P.run_min(S, D)
        for rr in R_BASE:
            out[(rr, D)] = m >= np.log(rr)
    return out


def kofn_masks(S):
    x = np.nan_to_num(S, nan=-np.inf)
    out = {}
    for rr in R_BASE:
        above = (x >= np.log(rr)).astype(np.int32)
        cs = np.concatenate([[0], np.cumsum(above)])
        for n in (10, 20, 30):
            cnt = cs[n:] - cs[:-n]; cnt = np.concatenate([np.zeros(n - 1, np.int32), cnt])
            for q in (0.5, 0.7, 0.85):
                out[(rr, n, q)] = cnt >= int(np.ceil(q * n))
    return out


def evaluate_all(rows, method):
    """per record: dict params -> (detected flags, n_fa)."""
    table = []
    for r in rows:
        S = r["S"]
        if method == "BASE":
            masks = build_masks(S)
        elif method == "KOFN":
            masks = kofn_masks(S)
        elif method == "DUAL":
            b = build_masks(S)
            A = [(rr, D) for rr in (2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0) for D in (2, 4, 6)]
            B = [(rr, D) for rr in (1.25, 1.5, 1.75, 2.0) for D in (10, 15, 20, 30)]
            masks = {(a, bb): b[a] | b[bb] for a in A for bb in B}
        d = {}
        for k, m in masks.items():
            det, fa, lat = score(onsets(m), r)
            d[k] = (det, fa, lat)
        table.append(d)
    return table


def loso(rows, table, target):
    subj = [RG.subject(r["case"]) for r in rows]
    keys = list(table[0].keys())
    det = {k: np.array([t[k][0].sum() for t in table]) for k in keys}
    fa = {k: np.array([t[k][1] for t in table]) for k in keys}
    nsz = np.array([len(r["seizures"]) for r in rows]); hrs = np.array([r["duration_s"] / 3600 for r in rows])
    held, choices = [], []
    for u in sorted(set(subj)):
        tr = np.array([s != u for s in subj]); te = ~tr
        best = None
        for k in keys:
            sens = det[k][tr].sum() / nsz[tr].sum(); fah = fa[k][tr].sum() / hrs[tr].sum()
            if fah <= target and (best is None or sens > best[0] or (sens == best[0] and fah < best[1])):
                best = (sens, fah, k)
        choices.append(dict(subject=u, params=str(best[2])))
        for i in np.flatnonzero(te):
            dd, ff, lat = table[i][best[2]]
            held.append(dict(n_sz=int(nsz[i]), detected=list(dd), n_fa=int(ff), hours=float(hrs[i]),
                             latency=lat, subject=u, i=int(i)))
    return held, choices


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--summaries", required=True)
    ap.add_argument("--channel", default="FP1-FP2")
    ap.add_argument("--perm", type=int, default=1000)
    a = ap.parse_args()
    res = Path(a.results); ch = a.channel
    allrec = [json.loads(l) for l in (res / "records.jsonl").read_text().splitlines() if l.strip()]
    rows = sorted([r for r in allrec if r["channel"] == ch and not r.get("missing")], key=lambda r: r["record"])
    times = file_times(a.summaries)
    deltas = {}
    for r in rows:
        z = np.load(res / "features" / f"{r['record']}_{ch}.npz")
        deltas[r["record"]] = P.per_second(z["fw_t10"], z["fw_diff10"], int(np.floor(r["duration_s"])))
    # contiguity (same case, gap ≤ 10 s)
    pred = {}
    byc = {}
    for r in rows:
        byc.setdefault(r["case"], []).append(r["record"])
    ncont = 0
    for c, recs in byc.items():
        recs = sorted(recs, key=lambda x: times.get(x, (1e12, 0))[0])
        for p_, q_ in zip(recs, recs[1:]):
            if p_ in times and q_ in times and 0 <= times[q_][0] - times[p_][1] <= 10:
                pred[q_] = p_; ncont += 1
    out = dict(channel=ch, contiguous_pairs=ncont, methods={}, choices={}, nulls={}, tests={})
    rig = json.loads((res / f"rigor_{ch}.json").read_text())
    for cont in (False, True):
        for r in rows:
            pre = deltas[pred[r["record"]]][-(WIN + LAG):] if (cont and r["record"] in pred) else None
            r["S"] = baseline_lr(deltas[r["record"]], pre)
        if cont:
            out["coldstart_seizures_cont"] = sum(1 for r in rows if r["record"] not in pred
                                                 for on, off in r["seizures"] if on < 335)
        for method in ("BASE", "KOFN", "DUAL"):
            tag = ("CONT_" if cont else "") + method
            table = evaluate_all(rows, method)
            for tgt in (1.0, 0.5, 0.2):
                held, ch_ = loso(rows, table, tgt)
                key = f"{tag}_{tgt}"
                for h in held:
                    h["alarms"] = []          # not needed for summaries
                out["methods"][key] = RG.summarise(held, rows)
                out["choices"][key] = ch_
                m = out["methods"][key]
                print(key, f"{100*m['sensitivity']:.1f}% @ {m['fa_per_hour']:.2f}  macro {100*m['macro_sensitivity']:.1f}%", flush=True)
                if tgt in (1.0, 0.5):
                    out["tests"][f"{key}_vs_DEV"] = RG.wilcoxon_subjects(m, rig["methods"][f"loso_DEV_{tgt}"])
                    py = "py_blackout" if tgt == 0.5 else "py_any"
                    out["tests"][f"{key}_vs_{py}"] = RG.wilcoxon_subjects(m, rig["methods"][py])
    (res / f"variants_{ch}.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
