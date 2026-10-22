"""
Proposed revision: line-length-ratio detector (LL-R), evaluated with
patient-wise 2-fold cross-validation.

Motivation (from the feature analysis): line-length is the only one of the
three Python features that separates ictal from inter-ictal EEG well on a
single frontal channel; the 2-of-3 vote with DAR/HFE suppresses it.

Detector (all causal, ESP32-feasible — one running median of 300 values @1 Hz):
  LL1(t)  = mean of the analyzer's line-length over each 1 s (10 ticks)
  BG(t)   = median of LL1 over [t−330 s, t−30 s]      (lagged background)
  R(t)    = LL1(t) / BG(t)
  alarm   when R ≥ r for D consecutive seconds (no alarms during the first 330 s)
Grid: r × D.  Folds: odd vs even CHB-MIT case number (chb01 & chb21 — same
subject — stay together).  On the training fold pick the (r, D) with the
highest sensitivity whose FA/h ≤ target; report it on the held-out fold.

usage: python ablation.py --results results [--channel FP1-F7]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scoring import MERGE_S, score_record, summarise                   # noqa: E402

R_GRID = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0]
D_GRID = [2, 4, 6, 8, 10, 15, 20]
BG_WIN, BG_LAG = 300, 30
FA_TARGETS = [1.0, 0.5, 0.2]


def ll_ratio(ft, ll, duration_s):
    n = int(np.floor(duration_s))
    sec = np.clip(ft.astype(np.int64), 0, n - 1)
    s = np.bincount(sec, weights=ll.astype(np.float64), minlength=n)
    c = np.bincount(sec, minlength=n)
    ll1 = np.where(c > 0, s / np.maximum(c, 1), np.nan)
    # forward-fill gaps (start-up)
    idx = np.where(np.isfinite(ll1), np.arange(n), 0); np.maximum.accumulate(idx, out=idx)
    ll1 = ll1[idx]
    import pandas as pd
    bg = pd.Series(ll1).rolling(BG_WIN, min_periods=BG_WIN // 2).median().shift(BG_LAG).to_numpy()
    r = ll1 / bg
    r[: BG_WIN + BG_LAG] = np.nan
    return r


def alarms_from_ratio(R, r, D):
    above = np.nan_to_num(R, nan=0.0) >= r
    # run length of consecutive 'above' seconds
    run = np.zeros(len(above), np.int32); cnt = 0
    for i, a in enumerate(above):
        cnt = cnt + 1 if a else 0
        run[i] = cnt
    onsets = np.where(run == D)[0].astype(float) + 1.0     # alarm at end of D-th second
    merged = []
    for a in onsets:
        if not merged or a - merged[-1] >= MERGE_S:
            merged.append(float(a))
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--channel", default="FP1-F7")
    a = ap.parse_args()
    res = Path(a.results)
    rows = [json.loads(l) for l in (res / "records.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r["channel"] == a.channel and not r.get("missing")]

    ratios = {}
    for r in rows:
        z = np.load(res / "features" / f"{r['record']}_{a.channel}.npz")
        ratios[r["record"]] = ratio = ll_ratio(z["ft"], z["ll"], r["duration_s"])

    def run(rs, rr, dd):
        sc = []
        for r in rs:
            al = alarms_from_ratio(ratios[r["record"]], rr, dd)
            s = score_record(al, [tuple(x) for x in r["seizures"]], r["duration_s"])
            s["case"] = r["case"]; sc.append(s)
        return summarise(sc)

    grid = {}
    for rr in R_GRID:
        for dd in D_GRID:
            s = run(rows, rr, dd)
            grid[(rr, dd)] = s
    fold = lambda r: int(r["case"][3:]) % 2 if r["case"] != "chb21" else 1
    out = dict(channel=a.channel, grid=[dict(r=k[0], D=k[1], sensitivity=v["sensitivity"],
                                             fa_per_hour=v["fa_per_hour"], latency_median=v["latency_median"])
                                        for k, v in grid.items()], cv={})
    md = [f"# LL-ratio detector — patient-wise 2-fold CV ({a.channel})\n",
          "| FA/h target (train) | Fold → params | Held-out sens. | Held-out FA/h | Held-out latency median (s) |",
          "|---|---|---|---|---|"]
    for tgt in FA_TARGETS:
        test_rows_all, chosen = [], []
        for f in (0, 1):
            train = [r for r in rows if fold(r) != f]; test = [r for r in rows if fold(r) == f]
            if not train or not test:
                continue
            best = None
            for rr in R_GRID:
                for dd in D_GRID:
                    s = run(train, rr, dd)
                    if s["fa_per_hour"] <= tgt and (best is None or s["sensitivity"] > best[0] or
                                                    (s["sensitivity"] == best[0] and s["fa_per_hour"] < best[1])):
                        best = (s["sensitivity"], s["fa_per_hour"], rr, dd)
            if best is None:
                continue
            chosen.append((f, best[2], best[3]))
            for r in test:
                al = alarms_from_ratio(ratios[r["record"]], best[2], best[3])
                s = score_record(al, [tuple(x) for x in r["seizures"]], r["duration_s"])
                s["case"] = r["case"]; test_rows_all.append(s)
        if not test_rows_all:
            continue
        s = summarise(test_rows_all)
        out["cv"][str(tgt)] = dict(chosen=chosen, **{k: v for k, v in s.items() if k != "per_case"})
        md.append(f"| ≤ {tgt} | " + "; ".join(f"fold{f}: r={rr}, D={dd}s" for f, rr, dd in chosen) +
                  f" | {s['detected']}/{s['seizures']} ({100*s['sensitivity']:.1f}%) | {s['fa_per_hour']:.2f} | "
                  f"{s['latency_median']:.1f} |")
    (res / "tables").mkdir(exist_ok=True)
    (res / "tables" / f"llr_cv_{a.channel}.md").write_text("\n".join(md) + "\n")
    (res / f"llr_{a.channel}.json").write_text(json.dumps(out, indent=2, default=float))

    # operating-curve figure with the original detectors' points
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from report import evaluate, _style, C_PY, C_FW, INK
    fig, ax = plt.subplots(figsize=(5.6, 4))
    pts = np.array([(v["fa_per_hour"], 100 * v["sensitivity"]) for v in grid.values()])
    order = np.argsort(pts[:, 0]); front = []; best = -1
    for i in order:
        if pts[i, 1] > best:
            front.append(pts[i]); best = pts[i, 1]
    front = np.array(front)
    ax.scatter(pts[:, 0], pts[:, 1], s=9, color="#b9b8b0", label="LL-R grid (all r, D)")
    ax.plot(front[:, 0], front[:, 1], color=INK, linewidth=1.2, label="LL-R best trade-off")
    for det, col, name in (("py", C_PY, "Python analyzer (as shipped)"), ("fw", C_FW, "ESP32 firmware (as shipped)")):
        s, _ = evaluate(rows, det, "seizure_alarms", a.channel)
        ax.scatter([s["fa_per_hour"]], [100 * s["sensitivity"]], s=60, color=col, zorder=5,
                   edgecolor="white", linewidth=1.5, label=name)
    ax.set_xscale("symlog", linthresh=0.1); ax.set_xlabel("False alarms per hour", fontsize=9)
    ax.set_ylabel("Seizures detected (%)", fontsize=9); ax.set_ylim(0, 102)
    _style(ax); ax.legend(frameon=False, fontsize=7.5, loc="lower right")
    fig.tight_layout(); fig.savefig(res / "figures" / f"operating_curve_{a.channel}.png", dpi=200); plt.close(fig)
    print("\n".join(md))


if __name__ == "__main__":
    main()
