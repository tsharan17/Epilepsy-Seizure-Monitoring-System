# LL-ratio detector — patient-wise 2-fold CV (FP2-F8)

| FA/h target (train) | Fold → params | Held-out sens. | Held-out FA/h | Held-out latency median (s) |
|---|---|---|---|---|
| ≤ 1.0 | fold0: r=2.5, D=15s; fold1: r=3.0, D=8s | 61/198 (30.8%) | 1.04 | 24.0 |
| ≤ 0.5 | fold0: r=3.5, D=15s; fold1: r=3.5, D=10s | 40/198 (20.2%) | 0.46 | 24.5 |
| ≤ 0.2 | fold0: r=4.0, D=15s; fold1: r=5.0, D=10s | 31/198 (15.7%) | 0.20 | 25.0 |
