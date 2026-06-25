# Vera — Open-Source EEG Seizure Monitor

A low-cost ESP32 + EEG front-end that detects seizure-like brain activity in real time, paired with a Python live-analysis dashboard and a Flutter companion app (**Vera**) for phone-based monitoring and alerts.

![Platform](https://img.shields.io/badge/platform-ESP32-blue?style=flat-square)
![Python](https://img.shields.io/badge/python-3.9%2B-yellow?style=flat-square)
![App](https://img.shields.io/badge/companion-Flutter%20APK-02569B?style=flat-square)
![Status](https://img.shields.io/badge/status-alpha%20prototype-orange?style=flat-square)

---

> ## ⚠️ Important Safety & Medical Disclaimer
> This is a **hobbyist / research prototype**, not a certified medical device. It has **not** been clinically validated and must **never** be used as someone's sole means of seizure detection or as a substitute for prescribed monitoring, medication, or professional medical care. There is no electrical isolation — when electrodes are touching skin, power the system **only from a USB battery bank**, never a mains-connected supply. False negatives (missed seizures) and false positives are both expected. If you or someone you care for has epilepsy, talk to a neurologist about appropriate monitoring equipment.

---

## 📦 What's in this repo

| File | Role |
|---|---|
| `seizure_monitor_v4.ino` | ESP32 firmware — EEG acquisition, on-device seizure state machine, WiFi AP + REST API |
| `seizure_monitor.py` | Python desktop analyzer — multi-feature classifier, live dashboard, alerts, session logging |
| `vera_app.apk` | "Vera" Android companion app (Flutter) — connects to the ESP32's WiFi hotspot for live status, waveform, and demo simulation |
| `PIN_CONNECTIONS.md` | Full wiring reference for the analog EEG front-end |

## 🧠 Overview

Three components talk to the same ESP32:

```
   EEG electrodes (FP1 / FP2 / Ear)
            │
   EXG BioAmp Pill → LM358 buffer → RC anti-alias filter
            │
        ESP32 (GPIO34 ADC, ~200 Hz)
   ┌────────┴─────────┐
   │                   │
 USB Serial         WiFi AP "Vera_EEG_Cap"
   │                   │
 seizure_monitor.py   vera_app.apk (phone)
 (deep multi-feature   (live status / waveform /
  analysis + dashboard) simulation, no internet needed)
```

The ESP32 always runs its own **lightweight on-device detector** so the RGB LED and emergency trigger pin work even with nothing else connected. The Python script adds a **heavier, more accurate classifier** for anyone running it on a laptop. The phone app is a **wireless front-end** for the same on-device detector — useful when a laptop isn't practical.

## 🔌 Hardware

Signal chain: `Ag/AgCl electrodes → EXG BioAmp Pill (gain ×1000) → LM358 voltage follower → 10 kΩ/100 nF RC filter (f_c ≈ 159 Hz) → ESP32 GPIO34 (12-bit ADC)`.

Full pin-by-pin wiring, the LM358 pinout, and the RC filter derivation are in **[`PIN_CONNECTIONS.md`](PIN_CONNECTIONS.md)**.

Additional ESP32 pins used by the v4 firmware (not in the original BCI build):

| GPIO | Function |
|---|---|
| 34 | EEG signal in (ADC1_CH6) |
| 35 | Battery voltage divider (ADC1_CH7) |
| 2 | Heartbeat LED |
| 18 | Mobile/BT trigger — 500 ms HIGH pulse on seizure onset |
| 25 / 26 / 27 | RGB status LED (Green / Red / Blue) |

## 🩺 How detection works

A four-state machine runs on both the firmware and the Python script:

```
NORMAL → BROWNOUT (pre-ictal/aura) → BLACKOUT (active seizure) → POST-ICTAL (recovery) → NORMAL
```

- **Firmware (on-device):** tracks an EMA baseline and the absolute deviation from it, fits an adaptive mean/σ model with a Welford EWMA estimator after a 90 s warm-up, and sets brownout/blackout thresholds at `μ + 2.5σ` and `μ + 4.0σ`. State changes require a run of confirming samples before they're accepted (debouncing).
- **Python (deeper analysis):** computes three EEG-literature seizure markers per analysis window — **Line-Length** (Gotman 1982), **delta/alpha power ratio** (ictal marker), and **high-frequency (gamma) energy ratio** — each with its own adaptively-learned threshold. A state change needs 2-of-3 markers to agree, plus several consecutive confirming ticks. Epochs with implausibly high line-length (motion/electrode disconnection) are flagged as artifacts and excluded from both classification and threshold learning, so a wire wiggle can't poison the adaptive model.

Both stages freeze their adaptive thresholds during a confirmed seizure so the seizure itself doesn't get learned as "normal."

## 📡 ESP32 firmware (`seizure_monitor_v4.ino`)

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

## 🖥️ Python analyzer (`seizure_monitor.py`)

```bash
pip install pyserial numpy scipy matplotlib requests
python seizure_monitor.py
```

- Reads the serial stream, runs Welch PSD + the three-marker classifier above on a rolling 512-sample buffer (analysis throttled to ~10 Hz to avoid sub-second state flicker).
- 11-panel live dashboard: raw EEG + baseline, diff signal, PSD, band-power bars, score history, line-length / DAR / HFE trend gauges with their live thresholds, seizure-state indicator, and a model-status panel (warm-up, frozen flag, artifact count, MCU's own reported state).
- Optional push alerts on state changes via any HTTP webhook (ntfy.sh, Pushover, etc.) — set `Config.alert_webhook`.
- Every state change and session start/end is appended to `seizure_session.jsonl` for later review.
- Edit the `Config` dataclass at the top of the file before running — at minimum set `port` (e.g. `COM3` on Windows, `/dev/ttyUSB0` on Linux/macOS).

## 📱 Vera app (`vera_app.apk`)

A Flutter Android app that talks directly to the ESP32 over WiFi — no pairing with the Python script needed.

- Connect your phone to the **`Vera_EEG_Cap`** WiFi network, then open the app.
- Polls `/status` for live state, battery, and seizure duration; pulls `/eeg` for a live waveform.
- Includes simulation buttons (NORMAL / BROWNOUT / BLACKOUT / POST-ICTAL) to demo the alert flow without needing a real seizure or even electrodes attached.
- Not distributed via Play Store — sideload by enabling "Install unknown apps" for your file manager/browser, then open the `.apk`.

## 🚀 Quick Start

1. Wire the analog front-end per **[`PIN_CONNECTIONS.md`](PIN_CONNECTIONS.md)**.
2. Flash `seizure_monitor_v4.ino` (Arduino IDE 2.x, `esp32` board package ≥ 2.0 — no extra libraries needed).
3. Power from a **USB battery bank** once electrodes are attached to skin.
4. Pick one (or both):
   - **Laptop route:** connect via USB, set `port` in `seizure_monitor.py`, run it.
   - **Phone route:** join the `Vera_EEG_Cap` WiFi network, install/open `vera_app.apk`.

## ⚠️ Known Limitations

- Single EEG channel — no spatial/multi-channel confirmation.
- Heuristic thresholds inspired by clinical literature (Shoeb 2009, Gotman 1982, Subasi 2005) — **not a validated clinical classifier**.
- No electrical isolation; battery power is mandatory with skin contact.
- WiFi AP uses a fixed, weak password — fine for a lab bench, not for unattended deployment.
- `vera_app.apk` is unsigned/sideloaded and Android-only.

## 🗺️ Roadmap

- [ ] Multi-channel acquisition
- [ ] BLE streaming as a WiFi alternative
- [ ] On-device software notch filter (50/60 Hz)
- [ ] EDF/BDF export for MNE-Python / EEGLAB
- [ ] Push notifications from the Vera app itself (currently status-poll only)

---

*Alpha-quality prototype — for research and hobbyist use only. Not for clinical or diagnostic use.*
