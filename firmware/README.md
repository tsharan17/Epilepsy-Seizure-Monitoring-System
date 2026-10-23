# Firmware

| Folder | What it is |
|---|---|
| `eeg_only/seizure_monitor_eeg/` | EEG-only firmware: acquisition, adaptive threshold state machine, Wi-Fi AP + REST API, RGB LED and trigger output |
| `eeg_motion/seizure_monitor_eeg_motion/` | Same firmware plus the MPU9250 driver and the baseline-normalized EEG/motion detectors |
| `mpu9250_bringup/` | Five-minute wiring check for the motion sensor |
| `tests/` | Host-side check of the detector against the Python evaluation code |
| `tools/serial_telemetry.py` | Logs the once-per-second `# [DET]` lines to CSV |

Both firmware sketches compile for **ESP32 Dev Module** with Arduino-ESP32 2.0.17 and no extra libraries:

| Sketch | Flash | Static RAM |
|---|---|---|
| `eeg_only` | 767 KB | 46.6 KB |
| `eeg_motion` | 792 KB | 48.7 KB (+ about 5 KB heap for the detector) |

They have been compiled; no on-device timing or bench measurement is reported.

## Wiring

See [`../hardware/PIN_CONNECTIONS.md`](../hardware/PIN_CONNECTIONS.md). The motion sensor adds four wires (3V3, GND, SDA = GPIO21, SCL = GPIO22, AD0 → GND); no EEG pin changes.

## Bring-up of the motion sensor

1. Flash `mpu9250_bringup/` and open the Serial Monitor at 115200 baud.
2. Expect `[SCAN] device at 0x68`, `WHO_AM_I=0x71 -> OK`, `|a| ≈ 1.00 g` when still, and the EEG loop rate (≈ 190–200 samples/s).
3. Flash `eeg_motion/seizure_monitor_eeg_motion/`. The boot log prints `# [IMU] MPU9250 found`; once per second a line `# [DET] fs=... dev=... eegR=... acc=... movR=... event=... conv=...` is printed.

## What the EEG-plus-motion firmware does

* Samples the IMU every 40 ms (25 Hz, 10 Hz digital low-pass, ±4 g, ±500 °/s).
* `motion_features.h`: per-second high-passed acceleration magnitude, gyroscope magnitude and 2–7 Hz rhythm share.
* `baseline_detector.h`: **DEV-BR** on the EEG deviation and **MOV-BR** on head acceleration, each divided by its own median over the previous 30–330 s. Two outputs, each at most once per 90 s and none in the first 330 s:
  * **event** (general mode): EEG ratio ≥ 2 for 20 s **or** motion ratio ≥ 24 with 2–7 Hz rhythm share ≥ 0.4 for 20 s → BROWNOUT (blue LED) for 60 s.
  * **convulsive alarm**: EEG ratio ≥ 4 **and** motion ratio ≥ 8 together for 30 s → BLACKOUT (red LED, 500 ms pulse on GPIO18, app) for 60 s, then POST-ICTAL.
* The parameters are the `EVT_*` and `CONV_*` constants at the top of the sketch. They are the values most often selected by leave-one-patient-out validation on SeizeIT2; the convulsive mode is exploratory (see the paper).
* `/status` adds `detector`, `alarmSource` (EEG/MOTION/BOTH), `eegRatio`, `motionRatio`, `motion`, `imu` (ok/absent) and `fs` (measured samples/s).
* Without an IMU the firmware runs EEG-only. `#define DETECTOR_MODE 0` restores the EEG-only state machine.
* The 5-field serial stream is unchanged, so `analyzer/seizure_monitor.py` still works.

## Host check

```bash
g++ -O2 -std=c++17 tests/baseline_detector_test.cpp -o baseline_detector_test
python ../evaluation/seizeit2/verify_cpp_detector.py <seizeit2_features_dir> ./baseline_detector_test
```

The C++ motion features match `s2_extract.py` to float precision, and the detector's alarm times match `s2_eval.py` exactly on all 2,850 SeizeIT2 recordings (`../evaluation/results/verify_cpp.json`) and 800/800 parameter-grid runs.
