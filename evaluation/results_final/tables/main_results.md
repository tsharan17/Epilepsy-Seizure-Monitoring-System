# Vera detector evaluation on CHB-MIT

24 patients · 165 recordings · 225.5 h · scoring: alarm within [onset−30 s, offset+60 s] = detection; alarms <90 s apart merged; all other alarms = false alarms.

### Channel FP1-F7

| Detector · alarm | Seizures detected | Mean per-patient sens. | False alarms | FA/h | FA/24 h | Latency median [IQR] (s) | Chance sens. at same alarm rate |
|---|---|---|---|---|---|---|---|
| Python analyzer (LL+DAR+HFE, 2-of-3) · BLACKOUT alarm | 14/198 (7.1%) | 16.6% | 127 | 0.56 | 13.5 | 29.1 [19.0, 62.6] | 2.3% |
| Python analyzer (LL+DAR+HFE, 2-of-3) · BROWNOUT-or-BLACKOUT alarm | 56/198 (28.3%) | 42.2% | 905 | 4.01 | 96.3 | 16.4 [7.5, 44.6] | 15.1% |
| ESP32 firmware (abs(x−EMA), μ+Kσ) · BLACKOUT alarm | 153/198 (77.3%) | 86.9% | 5506 | 24.42 | 586.1 | 23.3 [2.8, 54.0] | 61.5% |
| ESP32 firmware (abs(x−EMA), μ+Kσ) · BROWNOUT-or-BLACKOUT alarm | 183/198 (92.4%) | 94.6% | 6458 | 28.64 | 687.4 | 32.1 [7.5, 54.8] | 67.1% |

### Channel FP1-FP2

| Detector · alarm | Seizures detected | Mean per-patient sens. | False alarms | FA/h | FA/24 h | Latency median [IQR] (s) | Chance sens. at same alarm rate |
|---|---|---|---|---|---|---|---|
| Python analyzer (LL+DAR+HFE, 2-of-3) · BLACKOUT alarm | 11/194 (5.7%) | 9.6% | 71 | 0.32 | 7.7 | 26.3 [15.8, 34.0] | 1.3% |
| Python analyzer (LL+DAR+HFE, 2-of-3) · BROWNOUT-or-BLACKOUT alarm | 41/194 (21.1%) | 25.2% | 622 | 2.82 | 67.7 | 28.4 [15.3, 51.6] | 10.9% |
| ESP32 firmware (abs(x−EMA), μ+Kσ) · BLACKOUT alarm | 146/194 (75.3%) | 87.7% | 4032 | 18.29 | 438.9 | 14.5 [1.6, 47.7] | 51.5% |
| ESP32 firmware (abs(x−EMA), μ+Kσ) · BROWNOUT-or-BLACKOUT alarm | 165/194 (85.1%) | 92.8% | 5507 | 24.98 | 599.5 | 14.7 [0.3, 35.3] | 62.4% |

### Channel FP2-F8

| Detector · alarm | Seizures detected | Mean per-patient sens. | False alarms | FA/h | FA/24 h | Latency median [IQR] (s) | Chance sens. at same alarm rate |
|---|---|---|---|---|---|---|---|
| Python analyzer (LL+DAR+HFE, 2-of-3) · BLACKOUT alarm | 9/198 (4.5%) | 8.3% | 129 | 0.57 | 13.7 | 15.5 [10.3, 35.6] | 2.3% |
| Python analyzer (LL+DAR+HFE, 2-of-3) · BROWNOUT-or-BLACKOUT alarm | 58/198 (29.3%) | 40.3% | 864 | 3.83 | 92.0 | 19.5 [10.8, 42.7] | 14.5% |
| ESP32 firmware (abs(x−EMA), μ+Kσ) · BLACKOUT alarm | 164/198 (82.8%) | 88.3% | 5590 | 24.79 | 595.0 | 28.7 [4.0, 55.9] | 62.0% |
| ESP32 firmware (abs(x−EMA), μ+Kσ) · BROWNOUT-or-BLACKOUT alarm | 180/198 (90.9%) | 94.1% | 6487 | 28.77 | 690.5 | 23.4 [2.7, 50.2] | 67.3% |
