# Firmware v5 — EEG + MPU9250 head-motion alarm

`seizure_monitor_v5/` replaces `seizure_monitor_esp32_firmware/` (v4 is kept unchanged).
It compiles for **ESP32 Dev Module** with Arduino-ESP32 2.0.17 and no extra libraries
(flash 792 KB / 60 %, static RAM 48.7 KB plus ≈5 KB heap for the detector; v4: 767 KB, 46.6 KB).

## Wiring (adds four wires to the v4 board)

| MPU9250 pin | ESP32 pin | Note |
|---|---|---|
| VCC | 3V3 | the GY-9250 breakout has its own regulator; 3.3 V is fine |
| GND | GND | common ground with the BioAmp and battery |
| SDA | GPIO21 | I²C data (400 kHz) |
| SCL | GPIO22 | I²C clock |
| AD0 | GND | address 0x68 (tie to 3V3 for 0x69) |
| INT, NCS, FSYNC, EDA, ECL | not connected | polled at 25 Hz |

Mount the IMU **on the headband** (forehead or behind the ear), firmly, so it moves with
the head. Keep the I²C wires away from the electrode leads and the BioAmp input.
No v4 pin changes: GPIO34 EEG, 35 battery, 2 heartbeat, 18 mobile trigger, 25/26/27 RGB.

> The MPU-9250 is end-of-life at TDK. The driver also accepts the MPU-6500 and MPU-9255
> (same registers, WHO_AM_I 0x70 / 0x73), which are drop-in replacements.

## Bring-up (5 minutes)
1. Flash `mpu9250_bringup/` and open the Serial Monitor at 115200 baud.
2. Expect `[SCAN] device at 0x68`, `WHO_AM_I=0x71 -> OK`, `|a| ≈ 1.00 g` when still,
   and the EEG loop rate (≈190–200 samples/s with the `delay(5)` pacing).
3. Flash `seizure_monitor_v5/`. The boot log prints `# [IMU] MPU9250 found`.
   Once per second a `# [V5] fs=... dev=... eegR=... acc=... movR=... event=... conv=...` line is printed.

## What v5 does
* Samples the IMU every 40 ms (25 Hz, 10-Hz digital low-pass, ±4 g, ±500 °/s).
* `motion.h`: per-second high-passed acceleration magnitude, gyro magnitude, 2–7 Hz rhythm share.
* `vera_detect.h`: **DEV-BR** on the EEG deviation the v4 firmware already computes and
  **MOV-BR** on head acceleration, each divided by its own median over the previous 30–330 s.
  Two outputs, each at most once per 90 s, none in the first 330 s (warm-up):
  * **event** (general mode): EEG ratio ≥ 2 for 20 s **or** motion ratio ≥ 24 with 2–7 Hz rhythm share ≥ 0.4 for 20 s
    → BROWNOUT (blue LED) for 60 s. SeizeIT2, held-out patients: ≈31 % of all seizures at ≈1 false event/hour.
  * **convulsive alarm**: EEG ratio ≥ 4 **and** motion ratio ≥ 8 together for 30 s
    → BLACKOUT (red LED, 500-ms GPIO18 pulse, app) for 60 s, then POST-ICTAL.
    SeizeIT2: 76 % of focal-to-bilateral tonic–clonic seizures at ≈0.5 false alarms/day.
* `/status` adds `detector`, `alarmSource` (EEG/MOTION/BOTH), `eegRatio`, `motionRatio`,
  `motion`, `imu` (ok/absent) and `fs` (measured samples/s).
* Without an IMU, v5 runs EEG-only. `#define DETECTOR_MODE 0` restores v4 behaviour.
* The 5-field serial stream is unchanged, so `seizure_monitor.py` still works; `v5_telemetry.py`
  logs the `# [V5]` lines to CSV.

## Verification
`test/vera_detect_test.cpp` (host build: `g++ -O2 -std=c++17 test/vera_detect_test.cpp`)
reproduces the evaluation code: motion features match `s2_extract.py` to float precision, and
both outputs' alarm times match `s2_eval.py` exactly on all 2,850 SeizeIT2 recordings
(`evaluation/results_final/verify_cpp.json`). Not yet timed on the ESP32 (one 47-bin DFT and two
300-value `nth_element` per second).
Detector parameters are the ones selected by leave-one-subject-out on SeizeIT2.
