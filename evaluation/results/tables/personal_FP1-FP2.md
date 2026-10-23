# Ratio detectors and personalization — FP1-FP2

## A. Population thresholds, all recordings (patient-wise 2-fold CV)
| Signal | FA/h target | Params (fold0; fold1) | Detected | Sens. | FA/h | Latency (s) |
|---|---|---|---|---|---|---|
| LL | ≤1.0 | r=2.0,D=15; r=6.0,D=2 | 53/194 | 27.3% | 0.98 | 20.0 |
| DEV | ≤1.0 | r=1.5,D=15; r=1.5,D=15 | 92/194 | 47.4% | 0.87 | 18.0 |
| FUSE | ≤1.0 | r=1.5,D=20; r=2.5,D=10 | 72/194 | 37.1% | 0.81 | 23.5 |
| LL | ≤0.5 | r=2.5,D=15; r=3.5,D=10 | 47/194 | 24.2% | 0.47 | 25.0 |
| DEV | ≤0.5 | r=1.5,D=20; r=1.5,D=20 | 81/194 | 41.8% | 0.40 | 23.0 |
| FUSE | ≤0.5 | r=2.0,D=20; r=2.5,D=15 | 56/194 | 28.9% | 0.29 | 26.0 |
| LL | ≤0.2 | r=3.0,D=15; r=5.0,D=10 | 37/194 | 19.1% | 0.25 | 27.0 |
| DEV | ≤0.2 | r=2.0,D=20; r=2.5,D=15 | 59/194 | 30.4% | 0.18 | 25.0 |
| FUSE | ≤0.2 | r=2.5,D=15; r=2.5,D=20 | 58/194 | 29.9% | 0.23 | 27.0 |

## B. One caregiver-marked seizure (eval set: 24 patients, 165 seizures, 183.7 h)
| Method | FA/h target | Detected | Sens. | FA/h |
|---|---|---|---|---|
| population DEV | ≤1.0 | 74/165 | 44.8% | 0.82 |
| caregiver-tap DEV | ≤1.0 | 86/165 | 52.1% | 1.15 |
| population FUSE | ≤1.0 | 62/165 | 37.6% | 0.83 |
| caregiver-tap FUSE | ≤1.0 | 68/165 | 41.2% | 1.20 |
| population DEV | ≤0.5 | 65/165 | 39.4% | 0.39 |
| caregiver-tap DEV | ≤0.5 | 65/165 | 39.4% | 0.51 |
| population FUSE | ≤0.5 | 51/165 | 30.9% | 0.47 |
| caregiver-tap FUSE | ≤0.5 | 51/165 | 30.9% | 0.47 |

## C. Wearer-baseline self-calibration (eval set: 24 patients, 156 seizures, 149.5 h; first 2 recordings = wear-in)
| Method | FA/h target | Params | Detected | Sens. | FA/h | Latency (s) |
|---|---|---|---|---|---|---|
| population DEV | ≤1.0 | r=1.5,D=15; r=1.5,D=15 | 74/156 | 47.4% | 0.89 | 18.0 |
| self-calibrated DEV | ≤1.0 | q=0.5,D=20; q=0.5,D=20 | 81/156 | 51.9% | 0.72 | 24.0 |
| population FUSE | ≤1.0 | r=1.5,D=20; r=1.5,D=20 | 68/156 | 43.6% | 0.97 | 25.5 |
| self-calibrated FUSE | ≤1.0 | q=0.5,D=20; q=1.0,D=15 | 67/156 | 42.9% | 0.97 | 24.0 |
| population DEV | ≤0.5 | r=1.5,D=20; r=1.5,D=20 | 66/156 | 42.3% | 0.41 | 23.0 |
| self-calibrated DEV | ≤0.5 | q=0.25,D=20; q=0.25,D=20 | 47/156 | 30.1% | 0.29 | 29.0 |
| population FUSE | ≤0.5 | r=2.0,D=20; r=3.0,D=10 | 45/156 | 28.8% | 0.30 | 25.0 |
| self-calibrated FUSE | ≤0.5 | q=0.25,D=10; q=0.25,D=20 | 44/156 | 28.2% | 0.57 | 25.5 |
| population DEV | ≤0.2 | r=2.0,D=20; r=3.0,D=15 | 41/156 | 26.3% | 0.17 | 26.0 |
| self-calibrated DEV | ≤0.2 |  | 0/0 | nan% | nan | nan |
| population FUSE | ≤0.2 | r=3.0,D=10; r=4.0,D=10 | 45/156 | 28.8% | 0.31 | 23.0 |
| self-calibrated FUSE | ≤0.2 |  | 0/0 | nan% | nan | nan |
