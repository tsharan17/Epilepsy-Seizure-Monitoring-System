"""Example convulsive-mode alarm on a SeizeIT2 FBTC seizure (sleep onset preferred)."""
import sys, json, numpy as np
from pathlib import Path
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evaluation" / "seizeit2"))
import s2_eval as E
s2 = Path(sys.argv[1]); rows = E.load(s2)
rE, rM, D = 4.0, 8.0, 30
cands = []
for r in rows:
    if not r["mov"]: continue
    SE = np.nan_to_num(r["Se"], nan=-np.inf); SA = np.nan_to_num(r["Sa"], nan=-np.inf)
    al = E.onsets(E.runlen_ok((SE >= np.log(rE)) & (SA >= np.log(rM)), D))
    for (on, off), c, v in zip(r["seizures"], r["classes"], r["vig"]):
        if c != "FBTC/generalized" or on < 900: continue
        hit = [a for a in al if on - 30 <= a <= off + 60]
        fa_near = [a for a in al if abs(a - on) < 1800 and not (on - 30 <= a <= off + 60)]
        if hit and not fa_near:
            cands.append((v != "asleep", hit[0] - on, r, on, off, hit[0]))
cands.sort(key=lambda x: (x[0], x[1]))
_, lat, r, on, off, a = cands[0]
t0, t1 = int(on - 420), int(off + 240)
t = np.arange(t0, t1) - on
fig, ax = plt.subplots(2, 1, figsize=(3.5, 2.5), dpi=300, sharex=True)
for k, (S, rr, lab, col) in enumerate(((r["Se"], rE, "EEG ratio $e^{\\rho_\\delta}$", "#4c72b0"), (r["Sa"], rM, "motion ratio $e^{\\rho_\\alpha}$", "#dd8452"))):
    ax[k].semilogy(t, np.exp(S[t0:t1]), color=col, lw=0.8)
    ax[k].axhline(rr, color="k", lw=0.6, ls="--"); ax[k].text(t[0] + 5, rr * 1.25, f"r = {rr:g}", fontsize=5.5)
    ax[k].axvspan(0, off - on, color="#c44e52", alpha=0.15, lw=0)
    ax[k].axvline(a - on, color="#c44e52", lw=0.9)
    ax[k].set_ylabel(lab, fontsize=6); ax[k].tick_params(labelsize=5.5)
    for s in ("top", "right"): ax[k].spines[s].set_visible(False)
ax[0].text(a - on + 4, ax[0].get_ylim()[1] * 0.5, f"alarm +{a-on:.0f} s", fontsize=5.5, color="#c44e52")
ax[1].set_xlabel("time from annotated onset (s)", fontsize=6)
plt.tight_layout(h_pad=0.3)
plt.savefig(Path(__file__).parent / "figures" / "convulsive_example.png", bbox_inches="tight", pad_inches=0.02)
json.dump(dict(run=r["run"], onset=on, offset=off, alarm=a, vig=[v for (o, _), v in zip(r["seizures"], r["vig"]) if o == on][0],
               type=[ty for (o, _), ty in zip(r["seizures"], r["types"]) if o == on][0], n_candidates=len(cands)),
          open(Path(__file__).parent / "convulsive_example.json", "w"))
print(r["run"], on, off, a, len(cands))
