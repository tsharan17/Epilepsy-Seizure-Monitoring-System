"""Convulsive-mode detail: FBTC-level paired comparison, bootstrap CI, latency, sleep, per-subject FA.
Re-applies the per-fold LOSO choices stored in s2_results.json."""
import json, sys, ast, numpy as np
from pathlib import Path
from scipy.stats import binomtest, wilcoxon
sys.path.insert(0, str(Path(__file__).resolve().parent))
import s2_eval as E
s2 = Path(sys.argv[1]); D = json.load(open(s2 / "s2_results.json")); rows = E.load(s2)
subj_rows = {}
for i, r in enumerate(rows):
    subj_rows.setdefault(r["subject"], []).append(i)

def alarms(kind, key, r):
    SE = np.nan_to_num(r["Se"], nan=-np.inf)
    if kind == "EEG":
        return E.onsets(E.runlen_ok(SE >= np.log(key[0]), key[1]))
    if not r["mov"]:
        return np.array([])
    SA = np.nan_to_num(r["Sa"], nan=-np.inf)
    if kind == "MOV":
        a = SA >= np.log(key[0]); a = a & (r["rh"] >= key[2]) if key[2] > 0 else a
        return E.onsets(E.runlen_ok(a, key[1]))
    if kind == "COACT":
        return E.onsets(E.runlen_ok((SE >= np.log(key[0])) & (SA >= np.log(key[1])), key[2]))

res = {}
for kind, t in (("COACT", 0.02), ("EEG", 0.02), ("MOV", 0.02), ("COACT", 0.05)):
    ch = {c["subject"]: ast.literal_eval(c["key"]) for c in D["choices"][f"TC_{kind}_{t}"]}
    det, lat, vig, sub, fa, hrs = [], [], [], [], {}, {}
    for u, idx in subj_rows.items():
        fa[u] = 0; hrs[u] = 0.0
        for i in idx:
            r = rows[i]; al = alarms(kind, ch[u], r)
            d, f, l = E.score(al, r["seizures"]); fa[u] += f; hrs[u] += r["duration_s"] / 3600
            for k, c in enumerate(r["classes"]):
                if c == "FBTC/generalized":
                    det.append(bool(d[k])); lat.append(l[k]); vig.append(r["vig"][k]); sub.append(u)
    det = np.array(det); sub = np.array(sub); us = sorted(set(sub))
    rng = np.random.default_rng(0); bs = []
    for _ in range(2000):
        pick = rng.choice(us, len(us)); m = np.concatenate([det[sub == u] for u in pick]); bs.append(m.mean())
    tot_h = sum(hrs.values()); tot_fa = sum(fa.values())
    res[f"{kind}_{t}"] = dict(det=int(det.sum()), n=len(det), sens=float(det.mean()), ci=[float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
                              n_subj=len(us), lat_median=float(np.nanmedian(np.array(lat, float)[det])),
                              lat_iqr=[float(np.nanpercentile(np.array(lat, float)[det], q)) for q in (25, 75)],
                              sleep_det=int(det[np.array(vig) == "asleep"].sum()), sleep_n=int((np.array(vig) == "asleep").sum()),
                              fa_per_day=24 * tot_fa / tot_h,
                              subj_zero_fa=int(sum(1 for u in fa if fa[u] == 0)), n_subjects=len(fa),
                              median_subject_fa_day=float(np.median([24 * fa[u] / hrs[u] for u in fa])),
                              _det=det.tolist(), _sub=sub.tolist())
    print(kind, t, {k: v for k, v in res[f"{kind}_{t}"].items() if not k.startswith("_")})
# paired seizure-level exact McNemar: COACT vs EEG / MOV at 0.02
for b in ("EEG_0.02", "MOV_0.02"):
    a = np.array(res["COACT_0.02"]["_det"]); c = np.array(res[b]["_det"])
    n10 = int((a & ~c).sum()); n01 = int((~a & c).sum())
    p = binomtest(n10, n10 + n01, 0.5).pvalue if n10 + n01 else 1.0
    res[f"mcnemar_COACT_vs_{b}"] = dict(only_coact=n10, only_other=n01, p=float(p))
    print("McNemar COACT vs", b, n10, n01, p)
for k in list(res):
    if isinstance(res[k], dict):
        res[k] = {kk: v for kk, v in res[k].items() if not kk.startswith("_")}
(s2 / "s2_tc_detail.json").write_text(json.dumps(res, indent=1))
