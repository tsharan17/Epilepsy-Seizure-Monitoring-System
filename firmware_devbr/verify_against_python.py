import sys, json, subprocess, numpy as np
sys.path.insert(0, '../evaluation')
import personalize as P
from pathlib import Path
res = Path(sys.argv[1]); ch = 'FP1-FP2'
rows = [json.loads(l) for l in open(res/'records.jsonl')]
rows = [r for r in rows if r['channel']==ch and not r.get('missing')]
params = [(1.5,15),(1.5,20),(2.0,20),(2.5,15),(3.0,10)]
inp=[]; ref=[]
for r in rows:
    z=np.load(res/'features'/f"{r['record']}_{ch}.npz"); n=int(np.floor(r['duration_s']))
    dev=P.per_second(z['fw_t10'], z['fw_diff10'], n)
    S=P.log_ratio(dev)
    for rr,D in params:
        ref.append(P.alarms(S, np.log(rr), D))
        inp.append(f"{rr} {D} {n}\n" + " ".join('nan' if not np.isfinite(v) else repr(float(v)) for v in dev) + "\n")
out = subprocess.run(['./devbr_test'], input=''.join(inp), capture_output=True, text=True).stdout.split('\n')[:len(inp)]
mism=0; tot=0
for a,b in zip(ref,out):
    cpp=[float(x) for x in b.split()] if b.strip() else []
    tot+=len(a)
    if cpp!=a: mism+=1
print('cases',len(ref),'python alarms',tot,'mismatching cases',mism)
