"""Re-extract head motion for runs whose mov file has the neck accelerometer but no gyroscope."""
import json, sys, tempfile, numpy as np, pyedflib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(Path(__file__).resolve().parent))
import s2_extract as S
out = Path(sys.argv[1])
rows = [json.loads(l) for l in open(out / "meta.jsonl")]
todo = [x for x in rows if not x["mov"] and "GYR" in x.get("mov_err", "")]
print(len(todo), "runs to fix")

def fix(x):
    run = x["run"]; sub, ses = run.split("_")[:2]
    key = f"{S.DS}/{sub}/{ses}/mov/{run}_mov.edf"
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "m.edf"
        if not S.get(key, f):
            return run, None
        e = pyedflib.EdfReader(str(f)); ml = e.getSignalLabels()
        if "EEG SD ACC X" not in ml:
            e.close(); return run, None
        a = np.array([e.readSignal(ml.index(f"EEG SD ACC {c}")) for c in "XYZ"]); e.close()
    n = int(x["duration_s"])
    M = np.vstack([a, np.zeros_like(a)])
    acc, _, rhy = S.motion_feats(M, n)
    z = dict(np.load(out / "feat" / f"{run}.npz"))
    z.update(acc=acc, gyr=np.full(n, np.nan, np.float32), rhy=rhy)
    np.savez_compressed(out / "feat" / f"{run}.npz", **z)
    return run, True

with ThreadPoolExecutor(4) as ex:
    res = dict(ex.map(fix, todo))
ok = {k for k, v in res.items() if v}
for x in rows:
    if x["run"] in ok:
        x["mov"] = True; x["mov_note"] = "accelerometer only (no gyroscope channels)"; x.pop("mov_err", None)
(out / "meta.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows))
print("fixed", len(ok))
