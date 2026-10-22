"""What would more sensing buy?  DEV-BR on 1, 2 or 3 frontal bipolar channels (LOSO).
Channels combined per second via mean or max of their log-ratios, then the usual r/D rule."""
import json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rigor as RG, personalize as P
res = Path(sys.argv[1])
allrec = [json.loads(l) for l in (res / "records.jsonl").read_text().splitlines() if l.strip()]
by = {}
for r in allrec:
    if not r.get("missing"): by.setdefault(r["record"], {})[r["channel"]] = r
CH = ["FP1-FP2", "FP1-F7", "FP2-F8"]
rows = []
for rec, d in sorted(by.items()):
    if all(c in d for c in CH):
        r = dict(d["FP1-FP2"]); n = int(np.floor(r["duration_s"])); S = {}
        for c in CH:
            _, dev = RG.series(res, rec, c, n)
            S[c] = RG.baseline_score(dev)
        S["LR_mean"] = np.nanmean([S["FP1-F7"], S["FP2-F8"]], 0) if True else None
        S["LR_max"] = np.fmax(S["FP1-F7"], S["FP2-F8"])
        S["ALL_mean"] = np.mean([S[c] for c in CH], 0)
        S["ALL_max"] = np.fmax(np.fmax(S["FP1-FP2"], S["FP1-F7"]), S["FP2-F8"])
        S["FP_F7_mean"] = np.mean([S["FP1-FP2"], S["FP1-F7"]], 0)
        r["S"] = S; rows.append(r)
print(len(rows), "records", sum(len(r["seizures"]) for r in rows), "seizures", flush=True)
subs = sorted({RG.subject(r["case"]) for r in rows})
folds = [[i for i, r in enumerate(rows) if RG.subject(r["case"]) == u] for u in subs]
caches = {k: RG.Cache(rows, k) for k in rows[0]["S"]}
out = {}
for k in ["FP1-FP2", "FP_F7_mean", "LR_mean", "LR_max", "ALL_mean", "ALL_max"]:
    for t in (0.5, 1.0, 2.0):
        held, ch = RG.cv(caches, rows, folds, t, [k])
        m = RG.summarise(held, rows); out[f"{k}_{t}"] = m
        print(f"{k:11s} <= {t}: {100*m['sensitivity']:.1f}% @ {m['fa_per_hour']:.2f} FA/h  macro {100*m['macro_sensitivity']:.1f}%", flush=True)
for k in ["FP_F7_mean", "LR_mean", "ALL_mean", "ALL_max"]:
    for t in (0.5, 1.0):
        out[f"test_{k}_{t}"] = RG.wilcoxon_subjects(out[f"{k}_{t}"], out[f"FP1-FP2_{t}"])
        print(k, t, out[f"test_{k}_{t}"])
(res / "multichannel.json").write_text(json.dumps(out, indent=1, default=float))
