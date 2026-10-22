# Vera detector evaluation on CHB-MIT

3 patients · 9 recordings · 7.9 h · scoring: alarm within [onset−30 s, offset+60 s] = detection; alarms <90 s apart merged; all other alarms = false alarms.

### Channel FP1-F7

| Detector · alarm | Seizures detected | Mean per-patient sens. | False alarms | FA/h | FA/24 h | Latency median [IQR] (s) | Chance sens. at same alarm rate |
|---|---|---|---|---|---|---|---|
| Python analyzer (LL+DAR+HFE, 2-of-3) · BLACKOUT alarm | 3/9 (33.3%) | 14.3% | 7 | 0.88 | 21.2 | 17.8 [6.2, 32.2] | 3.7% |
| Python analyzer (LL+DAR+HFE, 2-of-3) · BROWNOUT-or-BLACKOUT alarm | 9/9 (100.0%) | 100.0% | 36 | 4.55 | 109.2 | 15.7 [8.9, 22.4] | 17.6% |
| ESP32 firmware (abs(x−EMA), μ+Kσ) · BLACKOUT alarm | 8/9 (88.9%) | 95.2% | 174 | 21.99 | 527.8 | -2.8 [-8.8, 2.9] | 60.5% |
| ESP32 firmware (abs(x−EMA), μ+Kσ) · BROWNOUT-or-BLACKOUT alarm | 9/9 (100.0%) | 100.0% | 226 | 28.56 | 685.5 | 3.8 [-7.8, 64.2] | 69.9% |

### Channel FP2-F8

| Detector · alarm | Seizures detected | Mean per-patient sens. | False alarms | FA/h | FA/24 h | Latency median [IQR] (s) | Chance sens. at same alarm rate |
|---|---|---|---|---|---|---|---|
| Python analyzer (LL+DAR+HFE, 2-of-3) · BLACKOUT alarm | 6/9 (66.7%) | 57.1% | 15 | 1.90 | 45.5 | 15.7 [10.6, 18.3] | 7.8% |
| Python analyzer (LL+DAR+HFE, 2-of-3) · BROWNOUT-or-BLACKOUT alarm | 6/9 (66.7%) | 57.1% | 46 | 5.81 | 139.5 | 5.8 [2.1, 7.1] | 22.0% |
| ESP32 firmware (abs(x−EMA), μ+Kσ) · BLACKOUT alarm | 8/9 (88.9%) | 95.2% | 192 | 24.27 | 582.4 | 7.2 [2.5, 21.2] | 64.0% |
| ESP32 firmware (abs(x−EMA), μ+Kσ) · BROWNOUT-or-BLACKOUT alarm | 9/9 (100.0%) | 100.0% | 240 | 30.33 | 728.0 | 27.3 [-14.7, 66.6] | 72.0% |
