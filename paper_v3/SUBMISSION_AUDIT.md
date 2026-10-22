# ICLT 2026 — multimodal paper (paper_v3) audit, 22 Oct 2026

This document covers what is new in `paper_v3` (EEG + MPU9250, SeizeIT2). Everything about the
CHB-MIT EEG part (dataset accounting, scoring, firmware port, references) is unchanged and
audited in `../paper_v2/SUBMISSION_AUDIT.md`.

* `iclt2026_multimodal.pdf` (`main.tex`): 5 pages incl. references (limit 6). **Submit this one.**
* `iclt2026_multimodal_4page.pdf` (`main4.tex`): 4 pages, only for the TCE / associated-journal route.
* The EEG-only paper (`../paper_v2`) is kept as a fallback.

## A. What changed versus paper_v2

| # | Change | Evidence |
|---|---|---|
| 1 | Title → "A Low-Cost EEG and Head-Motion Seizure Alarm: Code-Faithful Evaluation and an Embedded Multimodal Detector" | — |
| 2 | Hardware: MPU9250 on I²C (GPIO21/22, 0x68), 25 Hz, ±4 g, ±500 dps, 10-Hz DLPF. New system figure `figures/system_v5.png`. | `firmware_v5/seizure_monitor_v5/mpu9250.h` |
| 3 | Firmware v5: MPU9250 driver, motion features, DEV-BR + MOV-BR, general (OR) and convulsive (AND) outputs mapped to BROWNOUT / BLACKOUT; `/status` extended; v4 serial format unchanged. Compiles for ESP32 (Arduino-ESP32 2.0.17): 792 KB flash, 48.7 KB static RAM (v4: 767 KB / 46.6 KB) + ≈5 KB heap for the detector. | `arduino-cli compile`, no warnings in sketch code |
| 4 | Second dataset: SeizeIT2 (OpenNeuro ds005873, CC0): 125 patients, 2,850 recordings, 11,626 h, 883 annotated seizures, streamed and processed in the cloud. | `evaluation/seizeit2/s2_extract.py`, `results_final/seizeit2_meta.jsonl` |
| 5 | Detectors evaluated by LOSO on 125 patients: shipped firmware, DEV-BR (EEG), MOV-BR (accel, gyro), OR-fusion, AND co-activation; convulsive mode tuned for FBTC at 0.02–0.2 FA/h. | `evaluation/seizeit2/s2_eval.py` → `results_final/s2_results.json` |
| 6 | FBTC detail: bootstrap CI, latency, sleep, McNemar. | `s2_tc_detail.py` → `results_final/s2_tc_detail.json` |
| 7 | C++ verification: motion features vs Python (max rel. error 8×10⁻⁵, float32), detector alarms vs Python on all SeizeIT2 recordings with the shipped parameters. | `firmware_v5/test/vera_detect_test.cpp`, `verify_vera_cpp.py` → `results_final/verify_cpp.json` |
| 8 | Four new references, checked: Bhagubai et al. 2025 (arXiv:2502.01224; OpenNeuro DOI 10.18112/openneuro.ds005873.v1.1.0), Zhang et al. 2024 (arXiv:2403.13066), Beniczky et al. 2013 (Epilepsia 54(4):e58–61, doi 10.1111/epi.12120), InvenSense MPU-9250 product specification. | — |

## B. Headline numbers (all from the JSON files; nothing typed by hand)

| Claim | Value | Source |
|---|---|---|
| Shipped firmware on SeizeIT2 | 57.0 % at 7.01 FA/h (168/day); chance 29.9 % | `s2_results.json` → `FW` |
| EEG-or-motion at the firmware's alarm rate | 68.7 % at 6.28 FA/h; 53 patients better, 21 worse, p = 4×10⁻⁵ | `FUSED_atFW`, tests |
| General mode ≤1 FA/h | DEV-BR 33.1 %, MOV-BR 28.3 %, OR 31.1 % (OR vs EEG p = 0.06, *not* better) | `EEG_1.0`, `MOV_1.0`, `FUSED_1.0` |
| Convulsive mode (≤0.02 FA/h target) | **42/55 FBTC = 76.4 % [63–88 %] at 0.48 FA/day**, 37 patients, 20/25 from sleep, median latency 72 s; EEG-only 30.9 %, motion-only 23.6 % at the same rate (McNemar p = 4×10⁻⁷, 3×10⁻⁸) | `s2_tc_detail.json` |
| Convulsive mode (≤0.05 target) | 83.6 % [71–94 %] at 0.91/day | same |
| Modal firmware parameters | general: EEG r 2/D 20 or motion r 24/q 0.4/D 20 (106/125 folds); convulsive: r_E 4, r_M 8, D 30 (122/125) | `choices` |

## C. Claims the paper makes that rest on you (authors)

1. **"Built" for the MPU9250 headband.** You asked that the paper call the IMU built. I wrote it that
   way, and Table I says "built; not bench-characterized". This must be true when you submit:
   wire it as in `firmware_v5/README.md`, flash `mpu9250_bringup`, and check WHO_AM_I = 0x71 and
   |a| ≈ 1 g. If it is not built by then, change Table I to "designed" and "We extended" to
   "We designed an extension".
2. Nothing in the paper claims the device was worn or recorded seizures. Keep it that way unless
   you collect such data under ethics approval.

## D. Honest limitations stated in the paper

* Software replay only; no device, bench, timing or human data.
* SeizeIT2 ≠ the device: behind-the-ear EEG (not FP1–FP2), neck sensor at 25 Hz (not the headband), hospital setting.
* 386/2,850 SeizeIT2 recordings have no head-motion channels (motion cannot fire there); 124 have accelerometer
  without gyroscope (accelerometer used).
* Firmware parameters are modal LOSO choices from the same data (the reported numbers are held-out per patient,
  but the shipped constants are not validated on an independent cohort).
* FBTC results rest on 55 seizures in 37 patients; latency is from focal onset (72 s median), longer than clinical devices.
* Focal non-motor seizures: 15.7 % at ≤1 FA/h — the device is not useful for them.
* Example in Fig. "convulsive example" is selected (shortest-latency sleep FBTC without nearby false alarms); the caption says so.

## E. Unresolved / your action

1. Push `firmware_v5/`, `evaluation/seizeit2/`, `paper_v3/` to GitHub before submitting (data-availability statement).
2. Build and bring up the MPU9250 (C.1).
3. Optional, strengthens the paper a lot: one overnight self-recording with the headband (no seizures needed) to
   report the measured sampling rate, IMU noise and the false-alarm rate in real wear.
4. Change the Wi-Fi password in the firmware before any use.

## F. Checklist

- [x] IEEEtran conference, US letter, ≤ 6 pages incl. references (5)
- [x] Every number generated from result files (`numbers.tex`, `numbers_s2.tex`)
- [x] New references verified (publisher / arXiv / OpenNeuro)
- [x] AI-use disclosure
- [x] Fonts embedded (pdflatex Type 1)
- [ ] Code pushed to GitHub
- [ ] MPU9250 physically built and brought up (C.1)
- [ ] Submit on EDAS (https://edas.info/N35554) by 30 Oct 2026

## G. Reviewer risks

1. **No device data** (still the biggest risk). Mitigation: explicit status table and limitations; item E.3.
2. **Proxy dataset mismatch** (SeizeIT2 sensor sites). Mitigation: stated; the rule is unit- and gain-free by design.
3. **Below clinical sensitivity** (76 % vs 90–96 %). Mitigation: compared openly with clinical devices and the
   learned SeizeIT2 model; the contribution is the 6-KB rule at a clinical false-alarm rate.
4. **Novelty of baseline normalization.** Mitigation: prior art cited; novelty is code-faithful evaluation,
   unit-free transfer to motion, and the verified embedded co-activation alarm.
