# Vera — Open-Source EEG and Head-Motion Seizure Alarm

A low-cost ESP32 wearable with one forehead EEG channel and an optional MPU9250 head-motion sensor. It raises local alarms (LED and output pin), serves a small Wi-Fi API for a phone app, and streams data to a Python analyzer. The detection code has been evaluated by replaying public seizure recordings through it; see [`paper/`](paper/) and [`docs/audit_report.md`](docs/audit_report.md).

![Platform](https://img.shields.io/badge/platform-ESP32-blue?style=flat-square)
![Python](https://img.shields.io/badge/python-3.9%2B-yellow?style=flat-square)
![App](https://img.shields.io/badge/companion-Flutter%20APK-02569B?style=flat-square)
![Status](https://img.shields.io/badge/status-research%20prototype-orange?style=flat-square)

---

> ## ⚠️ Important Safety & Medical Disclaimer
> This is a **hobbyist / research prototype**, not a certified medical device. It has **not** been clinically validated and must **never** be used as someone's sole means of seizure detection or as a substitute for prescribed monitoring, medication, or professional medical care. There is no electrical isolation — when electrodes are touching skin, power the system **only from a USB battery bank**, never a mains-connected supply. False negatives (missed seizures) and false positives are both expected. If you or someone you care for has epilepsy, talk to a neurologist about appropriate monitoring equipment.

---

## Repository layout

| Folder | Contents |
|---|---|
| [`firmware/`](firmware/) | ESP32 firmware: `eeg_only/` (EEG state machine), `eeg_motion/` (EEG + MPU9250 detectors), `mpu9250_bringup/` (wiring check), `tests/` (host check of the detector), `tools/` (serial logger) |
| [`analyzer/`](analyzer/) | `seizure_monitor.py` — Python desktop analyzer and live dashboard |
| [`app/`](app/) | `vera_app.apk` — Android companion app |
| [`hardware/`](hardware/) | Wiring reference (`PIN_CONNECTIONS.md`) |
| [`evaluation/`](evaluation/) | Replay evaluation on CHB-MIT and SeizeIT2, stored results, and the audit scripts |
| [`paper/`](paper/) | LaTeX source, figures and PDF of the paper |
| [`docs/`](docs/) | Block and circuit diagrams, system diagram, audit report |

## Overview

```
   EEG electrodes (FP1 / FP2 / ear ground)         MPU9250 (I2C, optional)
            │                                         │
   EXG BioAmp Pill → LM358 buffer → RC filter         │
            │                                         │
            └──────────────► ESP32 ◄──────────────────┘
                     (GPIO34 ADC ~200 Hz, I2C 25 Hz)
                       ┌────────┴─────────┐
                  USB Serial        Wi-Fi AP "Vera_EEG_Cap"
                       │                  │
              analyzer/seizure_monitor.py   app/vera_app.apk
```

The ESP32 always runs its own on-device detector, so the RGB LED and the emergency output pin work with nothing else connected. The Python analyzer adds a heavier multi-feature classifier; the phone app is a wireless front-end for the on-device detector.

## Hardware

Signal chain: `Ag/AgCl electrodes → EXG BioAmp Pill (gain ×1000) → LM358 voltage follower → 10 kΩ/100 nF RC filter (f_c ≈ 159 Hz) → ESP32 GPIO34 (12-bit ADC)`. Optional motion sensor: MPU9250 on I²C (SDA GPIO21, SCL GPIO22, address 0x68). Full wiring is in [`hardware/PIN_CONNECTIONS.md`](hardware/PIN_CONNECTIONS.md).

| GPIO | Function |
|---|---|
| 34 | EEG signal in (ADC1_CH6) |
| 35 | Battery voltage divider (ADC1_CH7) |
| 2 | Heartbeat LED |
| 18 | Mobile/BT trigger — 500 ms HIGH pulse on seizure onset |
| 25 / 26 / 27 | RGB status LED (Green / Red / Blue) |
| 21 / 22 | I²C SDA / SCL for the MPU9250 |

## How detection works

A four-state machine runs on both the firmware and the Python script:

```
NORMAL → BROWNOUT (pre-ictal/aura) → BLACKOUT (active seizure) → POST-ICTAL (recovery) → NORMAL
```

- **EEG-only firmware (`firmware/eeg_only`):** tracks an EMA baseline and the absolute deviation from it, fits an adaptive mean/σ model after a 90 s warm-up, and sets brownout/blackout thresholds at `μ + 2.5σ` and `μ + 4.0σ`, with confirmation counters.
- **EEG-plus-motion firmware (`firmware/eeg_motion`):** adds a baseline-normalized detector. Each per-second signal (EEG deviation, head-acceleration magnitude) is divided by its own median over the previous 30–330 s, so no gain or per-user calibration is needed. A *general* event (EEG **or** motion) drives BROWNOUT; a *convulsive* alarm (EEG **and** motion together for 30 s) drives BLACKOUT. Set `DETECTOR_MODE 0` to restore the EEG-only behaviour. See [`firmware/README.md`](firmware/README.md).
- **Python analyzer:** three EEG markers per window — line-length, delta/alpha ratio and high-frequency energy ratio — each with an adaptive threshold; a state change needs 2 of 3 markers plus consecutive confirmations, and artifact epochs are excluded.

## Evidence and limits

All performance figures come from **software replay of public datasets**, not from the hardware:

- CHB-MIT (23 subjects, FP1–FP2 *derived* from bipolar channels): the baseline-normalized EEG detector reached 52.1 % of seizures at 0.97 false alarms/hour on held-out subjects.
- SeizeIT2 (125 patients, behind-the-ear EEG and a neck-worn motion sensor): the EEG-and-motion convulsive alarm detected 38 of 52 focal-to-bilateral tonic–clonic seizures at 0.51 false alarms/day. This analysis is exploratory.
- No bench measurements, no recordings from the device, and no human testing are included. The firmware has not been timed on the ESP32.

Details, caveats and how to reproduce are in [`evaluation/`](evaluation/) and [`docs/audit_report.md`](docs/audit_report.md).

## 📡 ESP32 firmware (`firmware/`)

- WiFi access point: **SSID `Vera_EEG_Cap`, password `12345678`**, IP `192.168.4.1` (no router/internet required)
- REST API (CORS-enabled, JSON):

  | Endpoint | Description |
  |---|---|
  | `GET /status` | Current state, battery %, seizure duration, active thresholds, simulation flag |
  | `GET /eeg` | Last 128 raw EEG samples (≈640 ms at 200 Hz) for waveform display |
  | `GET /simulate?state=NORMAL\|BROWNOUT\|BLACKOUT\|POST-ICTAL` | Forces the LED/API to report a given state for demos — the real detection pipeline keeps running underneath and is unaffected |

- Serial stream (115200 baud): `eegValue baseline diff state adaptThreshold`, one line per sample (~200 Hz). Lines starting with `#` are firmware debug logs and are ignored by the parser.
- Non-blocking RGB LED (green = normal, blue blink = brownout, red blink = blackout, purple blink = post-ictal) and a heartbeat LED that only pulses while NORMAL.
- Battery percentage from a voltage-divider on GPIO35, logged every 60 s.

## 🖥️ Python analyzer (`analyzer/seizure_monitor.py`)

```bash
pip install pyserial numpy scipy matplotlib requests
python analyzer/seizure_monitor.py
```

- Reads the serial stream, runs Welch PSD + the three-marker classifier above on a rolling 512-sample buffer (analysis throttled to ~10 Hz to avoid sub-second state flicker).
- 11-panel live dashboard: raw EEG + baseline, diff signal, PSD, band-power bars, score history, line-length / DAR / HFE trend gauges with their live thresholds, seizure-state indicator, and a model-status panel (warm-up, frozen flag, artifact count, MCU's own reported state).
- Optional push alerts on state changes via any HTTP webhook (ntfy.sh, Pushover, etc.) — set `Config.alert_webhook`.
- Every state change and session start/end is appended to `seizure_session.jsonl` for later review.
- Edit the `Config` dataclass at the top of the file before running — at minimum set `port` (e.g. `COM3` on Windows, `/dev/ttyUSB0` on Linux/macOS).

## 📱 Vera app (`app/vera_app.apk`)

A Flutter Android app that talks directly to the ESP32 over WiFi — no pairing with the Python script needed.

- Connect your phone to the **`Vera_EEG_Cap`** WiFi network, then open the app.
- Polls `/status` for live state, battery, and seizure duration; pulls `/eeg` for a live waveform.
- Includes simulation buttons (NORMAL / BROWNOUT / BLACKOUT / POST-ICTAL) to demo the alert flow without needing a real seizure or even electrodes attached.
- Not distributed via Play Store — sideload by enabling "Install unknown apps" for your file manager/browser, then open the `.apk`.

## Quick start

1. Wire the analog front-end per [`hardware/PIN_CONNECTIONS.md`](hardware/PIN_CONNECTIONS.md) (and the MPU9250 if you use it).
2. Flash `firmware/eeg_motion/seizure_monitor_eeg_motion` (or `firmware/eeg_only/seizure_monitor_eeg` for EEG only) with Arduino IDE 2.x and the `esp32` board package 2.0.x; no extra libraries are needed. Change the Wi-Fi password first.
3. Power from a **USB battery bank** once electrodes are on skin.
4. Pick one or both:
   - **Laptop:** connect via USB, set `port` in `analyzer/seizure_monitor.py`, run it.
   - **Phone:** join the `Vera_EEG_Cap` Wi-Fi network, install and open `app/vera_app.apk`.

## Known limitations

- One EEG channel; no spatial confirmation.
- Heuristic thresholds inspired by the literature (Shoeb 2009, Gotman 1982, Subasi 2005); not a validated clinical classifier.
- No electrical isolation; battery power is mandatory with skin contact.
- The Wi-Fi AP uses a fixed, weak password (`12345678`) — change it before any real use.
- The APK is unsigned, sideloaded and Android-only.

## Roadmap

- [ ] Bench characterization of the amplifier and the motion sensor
- [ ] Overnight recordings and an ethics-approved study
- [ ] Multi-channel acquisition and BLE streaming
- [ ] On-device 50/60 Hz notch filter
- [ ] EDF/BDF export; push notifications from the app

## License

See [`LICENSE`](LICENSE).

---

*Research prototype — not for clinical or diagnostic use.*
