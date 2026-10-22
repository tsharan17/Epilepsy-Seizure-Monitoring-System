"""In-sample operating grid on the rigor.py parameter grid (for the trade-off figure)."""
import json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rigor as RG, personalize as P
res = Path(sys.argv[1]); ch = "FP1-FP2"
recs = [json.loads(l) for l in (res / "records.jsonl").read_text().splitlines() if l.strip()]
rows = sorted([r for r in recs if r["channel"] == ch and not r.get("missing")], key=lambda r: r["record"])
for r in rows:
    n = int(np.floor(r["duration_s"])); ll, dev = RG.series(res, r["record"], ch, n)
    r["S"] = {"LL": RG.baseline_score(ll), "DEV": RG.baseline_score(dev)}
out = {}
for sig in ("LL", "DEV"):
    c = RG.Cache(rows, sig); g = []
    for rr in RG.R_GRID:
        for D in RG.D_GRID:
            sens, fah = RG.agg(RG.score_set(c, list(range(len(rows))), np.log(rr), D))
            g.append(dict(r=rr, D=D, sensitivity=sens, fa_per_hour=fah))
    out[sig] = g
(res / "grid_FP1-FP2.json").write_text(json.dumps(out))
print("ok")
