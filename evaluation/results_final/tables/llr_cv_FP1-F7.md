# LL-ratio detector — patient-wise 2-fold CV (FP1-F7)

| FA/h target (train) | Fold → params | Held-out sens. | Held-out FA/h | Held-out latency median (s) |
|---|---|---|---|---|
| ≤ 1.0 | fold0: r=2.0, D=20s; fold1: r=3.0, D=8s | 63/198 (31.8%) | 0.83 | 25.0 |
| ≤ 0.5 | fold0: r=2.5, D=20s; fold1: r=3.5, D=10s | 44/198 (22.2%) | 0.37 | 29.0 |
| ≤ 0.2 | fold0: r=3.5, D=20s; fold1: r=5.0, D=10s | 30/198 (15.2%) | 0.16 | 32.5 |
