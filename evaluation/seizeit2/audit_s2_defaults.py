"""Firmware default convulsive settings (r_E=4, r_M=8, D=30 s) applied to motion-equipped recordings; NOT held out (parameters came from all-recordings analysis)."""
import sys, json, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import s2_eval as E
rows = [r for r in E.load(Path(sys.argv[1])) if r["mov"]]
det = n = fa = 0; h = 0.0
for r in rows:
    SE = np.nan_to_num(r["Se"], nan=-np.inf); SA = np.nan_to_num(r["Sa"], nan=-np.inf)
    al = E.onsets(E.runlen_ok((SE >= np.log(4.0)) & (SA >= np.log(8.0)), 30))
    d, f, lat = E.score(al, r["seizures"]); fa += f; h += r["duration_s"]/3600
    for k, c in enumerate(r["classes"]):
        if c == "FBTC/generalized": n += 1; det += int(d[k])
o = dict(det=det, n=n, fa=fa, hours=h, fa_per_day=24*fa/h); print(o); Path(sys.argv[2]).write_text(json.dumps(o))
