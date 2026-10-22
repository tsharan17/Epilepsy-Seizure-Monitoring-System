"""
Baseline-normalized feature fusion (BR-LR) on the primary channel.

Every per-second feature is converted to a scale-free log-ratio against its own
delayed running median (window 300 s, lag 30 s), plus short causal context
(5-s and 20-s running means).  A logistic-regression model (one dot product per
second — ESP32-feasible) maps them to a seizure probability p(t); an alarm is
raised when p ≥ θ for D consecutive seconds.

Validation (no information from the held-out subject is used):
  outer loop  leave-one-subject-out (23 folds, chb01+chb21 = one subject)
  inner loop  2-fold by subject inside the 22 training subjects → out-of-fold
              probabilities → choose (θ, D) meeting the FA/h target
  then refit on all 22 training subjects and apply (θ, D) to the held-out one.

Feature sets:
  FW   features derived only from the firmware deviation d (already on-device)
  ALL  FW + analyzer features (line-length, delta/alpha, high-frequency energy)
  ALL-GBM  same features, gradient-boosted trees (non-embedded upper reference)

usage: python fusion.py --results results [--channel FP1-FP2]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scoring import score_record                                     # noqa: E402
import personalize as P                                              # noqa: E402
import rigor as RG                                                   # noqa: E402

WIN, LAG = 300, 30
DEAD = WIN + LAG


def per_second_stats(t, x, n):
    sec = np.clip(t.astype(np.int64), 0, n - 1)
    df = pd.DataFrame({"s": sec, "x": x.astype(np.float64)})
    g = df.groupby("s")["x"]
    out = {}
    for k, f in (("mean", g.mean()), ("max", g.max()), ("std", g.std())):
        y = np.full(n, np.nan); y[f.index.values] = f.values
        out[k] = pd.Series(y).ffill().to_numpy()
    return out


def lr(y):
    bg = pd.Series(y).rolling(WIN, min_periods=WIN // 2).median().shift(LAG).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.log(np.maximum(y, 1e-9) / np.maximum(bg, 1e-9))
    return r


def ctx(x, w):
    return pd.Series(x).rolling(w, min_periods=1).mean().to_numpy()


def features(res, rec, ch, dur):
    z = np.load(res / "features" / f"{rec}_{ch}.npz")
    n = int(np.floor(dur))
    dev = per_second_stats(z["fw_t10"], z["fw_diff10"], n)
    ll = per_second_stats(z["ft"], z["ll"], n)
    dar = per_second_stats(z["ft"], z["dar"], n)
    hfe = per_second_stats(z["ft"], z["hfe"], n)
    F = {}
    F["dev_mean"] = lr(dev["mean"]); F["dev_max"] = lr(dev["max"]); F["dev_std"] = lr(np.nan_to_num(dev["std"]) + 1e-3)
    F["dev_c5"] = ctx(F["dev_mean"], 5); F["dev_c20"] = ctx(F["dev_mean"], 20)
    fw_cols = list(F)
    F["ll_mean"] = lr(ll["mean"]); F["ll_c5"] = ctx(F["ll_mean"], 5); F["ll_c20"] = ctx(F["ll_mean"], 20)
    F["dar_lr"] = lr(dar["mean"]); F["hfe_lr"] = lr(hfe["mean"] + 1e-4)
    F["dar_log"] = np.log(np.maximum(dar["mean"], 1e-6)); F["hfe_log"] = np.log(np.maximum(hfe["mean"], 1e-6))
    X = np.column_stack([F[k] for k in F]).astype(np.float32)
    X[:DEAD] = np.nan
    return X, list(F), fw_cols


def labels(n, seizures):
    y = np.zeros(n, np.int8); keep = np.ones(n, bool)
    for on, off in seizures:
        y[int(on):int(off) + 1] = 1
        keep[max(0, int(on) - 60):int(on)] = False
        keep[int(off) + 1:min(n, int(off) + 121)] = False
    return y, keep


class Model:
    def __init__(self, kind):
        self.kind = kind

    def fit(self, X, y):
        if self.kind == "lr":
            from sklearn.linear_model import LogisticRegression
            self.mu = X.mean(0); self.sd = X.std(0) + 1e-6
            self.m = LogisticRegression(C=0.1, class_weight="balanced", max_iter=500).fit((X - self.mu) / self.sd, y)
        else:
            from sklearn.ensemble import HistGradientBoostingClassifier
            self.m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
                                                    class_weight="balanced", random_state=0).fit(X, y)
        return self

    def p(self, X):
        out = np.full(len(X), np.nan, np.float32)
        ok = np.all(np.isfinite(X), 1)
        if ok.any():
            Z = X[ok] if self.kind != "lr" else (X[ok] - self.mu) / self.sd
            out[ok] = self.m.predict_proba(Z)[:, 1]
        return out


TH_Q = np.round(np.concatenate([np.arange(0.5, 0.95, 0.05), np.arange(0.95, 1.0, 0.005)]), 3)
D_GRID = [1, 2, 4, 6, 10, 15, 20]


def train_set(rows, idx, cols, rng, neg_frac=0.15):
    Xs, ys = [], []
    for i in idx:
        r = rows[i]; X = r["X"][:, cols]
        ok = r["keep"] & np.all(np.isfinite(X), 1)
        sel = ok & ((r["y"] == 1) | (rng.random(len(ok)) < neg_frac))
        Xs.append(X[sel]); ys.append(r["y"][sel])
    return np.concatenate(Xs), np.concatenate(ys)


def choose(rows, idx, P_by_i, target):
    """pick (θ, D) maximizing sensitivity with FA/h ≤ target on out-of-fold probabilities."""
    allp = np.concatenate([P_by_i[i][np.isfinite(P_by_i[i])] for i in idx])
    ths = np.unique(np.quantile(allp, TH_Q))
    best = None
    for D in D_GRID:
        mins = {i: P.run_min(P_by_i[i], D) for i in idx}
        for th in ths:
            det = nsz = fa = 0; h = 0.0
            for i in idx:
                al = RG.alarms_from_min(mins[i], th)
                s = score_record(al, [tuple(x) for x in rows[i]["seizures"]], rows[i]["duration_s"])
                det += sum(s["detected"]); nsz += s["n_sz"]; fa += s["n_fa"]; h += s["hours"]
            sens, fah = det / max(nsz, 1), fa / h
            if fah <= target and (best is None or sens > best[0]):
                best = (sens, fah, float(th), D)
    return best


def run(rows, subjects, cols, kind, targets, seed=0):
    rng = np.random.default_rng(seed)
    held = {t: [] for t in targets}; choices = {t: [] for t in targets}
    for u in subjects:
        te = [i for i, r in enumerate(rows) if RG.subject(r["case"]) == u]
        tr = [i for i, r in enumerate(rows) if RG.subject(r["case"]) != u]
        trs = sorted({RG.subject(rows[i]["case"]) for i in tr})
        half = set(trs[::2])
        A = [i for i in tr if RG.subject(rows[i]["case"]) in half]; B = [i for i in tr if i not in set(A)]
        oof = {}
        for fit_idx, pred_idx in ((A, B), (B, A)):
            m = Model(kind).fit(*train_set(rows, fit_idx, cols, rng))
            for i in pred_idx:
                oof[i] = m.p(rows[i]["X"][:, cols])
        m = Model(kind).fit(*train_set(rows, tr, cols, rng))
        pt = {i: m.p(rows[i]["X"][:, cols]) for i in te}
        for t in targets:
            b = choose(rows, tr, oof, t)
            choices[t].append(dict(subject=u, th=b[2], D=b[3], inner_sens=b[0], inner_fah=b[1]))
            for i in te:
                al = RG.alarms_from_min(P.run_min(pt[i], b[3]), b[2])
                s = score_record(al, [tuple(x) for x in rows[i]["seizures"]], rows[i]["duration_s"])
                s["subject"] = u; s["alarms"] = al; s["i"] = i
                held[t].append(s)
        print("  fold", u, "done", flush=True)
    return held, choices


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--channel", default="FP1-FP2")
    ap.add_argument("--perm", type=int, default=1000)
    ap.add_argument("--kinds", default="lr_fw,lr_all,gbm_all")
    a = ap.parse_args()
    res = Path(a.results); ch = a.channel
    allrec = [json.loads(l) for l in (res / "records.jsonl").read_text().splitlines() if l.strip()]
    rows = sorted([r for r in allrec if r["channel"] == ch and not r.get("missing")], key=lambda r: r["record"])
    names = fwc = None
    for r in rows:
        X, names, fwc = features(res, r["record"], ch, r["duration_s"])
        r["X"] = X; r["y"], r["keep"] = labels(len(X), r["seizures"])
    subjects = sorted({RG.subject(r["case"]) for r in rows})
    col_sets = {"fw": [names.index(c) for c in fwc], "all": list(range(len(names)))}
    out = dict(channel=ch, features=names, fw_features=fwc, methods={}, choices={}, nulls={}, tests={})
    targets = (1.0, 0.5, 0.2)
    rig = json.loads((res / f"rigor_{ch}.json").read_text()) if (res / f"rigor_{ch}.json").exists() else None
    for kind_set in a.kinds.split(","):
        kind, cs = kind_set.split("_")
        print(kind_set, flush=True)
        held, ch_ = run(rows, subjects, col_sets[cs], kind, targets)
        for t in targets:
            key = f"{kind_set}_{t}"
            out["methods"][key] = RG.summarise(held[t], rows)
            out["choices"][key] = ch_[t]
            print(key, f"{100*out['methods'][key]['sensitivity']:.1f}% @ {out['methods'][key]['fa_per_hour']:.2f}"
                  f" macro {100*out['methods'][key]['macro_sensitivity']:.1f}%", flush=True)
            if t in (1.0, 0.5):
                out["nulls"][key] = RG.null_test(held[t], rows, a.perm)
                if rig:
                    out["tests"][f"{key}_vs_DEV"] = RG.wilcoxon_subjects(out["methods"][key], rig["methods"][f"loso_DEV_{t}"])
                    py = "py_blackout" if t == 0.5 else "py_any"
                    out["tests"][f"{key}_vs_{py}"] = RG.wilcoxon_subjects(out["methods"][key], rig["methods"][py])
        # coefficients of the final all-subject LR (for the paper: interpretability / embedded cost)
        if kind == "lr":
            rng = np.random.default_rng(0)
            m = Model("lr").fit(*train_set(rows, list(range(len(rows))), col_sets[cs], rng))
            out[f"coef_{kind_set}"] = dict(zip([names[c] for c in col_sets[cs]], (m.m.coef_[0] / m.sd).tolist()))
    (res / f"fusion_{ch}.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
