"""Check firmware v5's vera_detect.h against s2_eval.py on SeizeIT2 per-second data.
usage: python verify_vera_cpp.py S2OUT BINARY [n_records]"""
import sys, subprocess, json, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import s2_eval as E

s2, binp = Path(sys.argv[1]), sys.argv[2]
nrec = int(sys.argv[3]) if len(sys.argv) > 3 else 10**9
rows = E.load(s2)[:nrec]
PARAMS = [(3.0, 20, 8.0, 10, 0.4, 2.0, 8.0, 10), (2.0, 10, 4.0, 5, 0.0, 1.5, 3.0, 5), (6.0, 30, 16.0, 20, 0.3, 3.0, 16.0, 20), (1.5, 4, 24.0, 3, 0.5, 4.0, 2.0, 3)]
if len(sys.argv) > 4:
    PARAMS = json.loads(sys.argv[4])
lines, expect = [], []
for r in rows:
    z = np.load(s2 / "feat" / f"{r['run']}.npz"); n = len(r["Se"])
    dev = z["dev0"][:n]
    acc = z["acc"][:n] if r["mov"] else np.full(n, np.nan); rhy = z["rhy"][:n] if r["mov"] else np.full(n, np.nan)
    body = "\n".join(f"{a:.9g} {b:.9g} {c:.9g}" for a, b, c in zip(dev, acc, rhy))
    for (rE, DE, rM, DM, qM, rEc, rMc, DC) in PARAMS:
        lines.append(f"{rE} {DE} {rM} {DM} {qM} {int(r['mov'])} {rEc} {rMc} {DC}\n{n}\n{body}")
        me = E.runlen_ok(np.nan_to_num(r["Se"], nan=-np.inf) >= np.log(rE), DE)
        if r["mov"]:
            a = (np.nan_to_num(r["Sa"], nan=-np.inf) >= np.log(rM))
            if qM > 0:
                a &= r["rh"] >= qM
            mm = E.runlen_ok(a, DM)
        else:
            mm = np.zeros(n, bool)
        if r["mov"]:
            cc = (np.nan_to_num(r["Se"], nan=-np.inf) >= np.log(rEc)) & (np.nan_to_num(r["Sa"], nan=-np.inf) >= np.log(rMc))
            ec = E.onsets(E.runlen_ok(cc, DC))
        else:
            ec = np.array([])
        expect.append((E.onsets(me | mm), ec))
out = "".join(subprocess.run([binp], input=l + "\n", capture_output=True, text=True).stdout for l in lines)
got, ce, cc = [], [], []
for l in out.splitlines():
    if l == "END":
        got.append((np.array(ce), np.array(cc))); ce, cc = [], []
    elif l.startswith("E "):
        ce.append(float(l[2:]))
    elif l.startswith("C "):
        cc.append(float(l[2:]))
eq = lambda g, e: len(g) == len(e) and (len(g) == 0 or np.allclose(g, e))
same = sum(eq(g[0], e[0]) and eq(g[1], e[1]) for g, e in zip(got, expect))
res = dict(records=len(rows), runs=len(expect), identical=int(same),
           alarms=int(sum(len(e[0]) + len(e[1]) for e in expect)))
print(res)
(s2 / "verify_cpp.json").write_text(json.dumps(res))
