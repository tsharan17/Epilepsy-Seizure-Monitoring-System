"""
EEG Epilepsy Seizure Monitor — Python Analyzer
════════════════════════════════════════════════════════════════════════════════
Builds on bci_v2.py with full epilepsy seizure detection:

  • BROWNOUT  — pre-ictal / aura phase (warning)
  • BLACKOUT  — ictal phase (active seizure, call for help)
  • POST-ICTAL — recovery phase after seizure

Threshold basis (clinical literature):
  ─────────────────────────────────────────────────────────────────────
  Metric              Normal          Brownout        Blackout
  ─────────────────────────────────────────────────────────────────────
  Line-length (LL)    baseline        > μ + 2.5σ      > μ + 4.0σ
  Band power ratio    baseline        δ/α > 2.5       δ/α > 4.5
  High-freq energy    baseline        HFE > μ + 2σ    HFE > μ + 3.5σ
  Beta spike          < 0.35          0.35–0.55       > 0.55
  ─────────────────────────────────────────────────────────────────────
  Sources: Shoeb 2009 (CHB-MIT), Subasi 2005 (wavelet-SVM),
           Gotman 1982 (line-length detector), Iasemidis 2003.

Adaptive learning:
  An online Welford estimator (mean + variance) is maintained per
  feature channel.  After a 90-second warm-up, thresholds are
  recalculated every 30 seconds as:
      brownout = μ + K_warn  × σ
      blackout = μ + K_alarm × σ
  where K_warn=2.5 and K_alarm=4.0 are the clinical z-score multipliers.
  The estimator uses exponential forgetting (α=0.995) so it tracks
  slow drift (electrode impedance, posture) without drifting during
  a real seizure (which is bounded by MAX_BLACKOUT_HOLD).

Mobile alerts:
  Send HTTP POST to a companion URL (e.g. ntfy.sh topic, Pushover, or
  any webhook).  Set ALERT_WEBHOOK below.  Leave empty to disable.

Requirements:
  pip install pyserial numpy scipy matplotlib requests

Usage:
  1. Flash seizure_monitor.ino to ESP32
  2. Edit port / ALERT_WEBHOOK below
  3. python seizure_monitor.py
"""

# ─────────────────────────────────────────────────────────────────────────────
# Backend must be set before pyplot import
# ─────────────────────────────────────────────────────────────────────────────
import matplotlib
matplotlib.use("TkAgg")   # swap to "Qt5Agg" + pip install pyqt5 if TkAgg missing

# ─────────────────────────────────────────────────────────────────────────────
# Imports
# ─────────────────────────────────────────────────────────────────────────────
import sys
import time
import json
import logging
import threading
import datetime
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.animation as animation
import matplotlib.patches as mpatches
from scipy.signal import welch, butter, filtfilt
import serial

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

# ─────────────────────────────────────────────────────────────────────────────
# NumPy 2.x compatibility
# ─────────────────────────────────────────────────────────────────────────────
_trapz = getattr(np, "trapezoid", None) or getattr(np, "trapz", None)


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Config:
    # ── Serial ────────────────────────────────────────────────────────────────
    port:      str = "COM3"        # ← Change to your port (Linux: /dev/ttyUSB0)
    baud_rate: int = 115_200

    # ── Signal ────────────────────────────────────────────────────────────────
    sample_rate:    int = 200      # Must match ESP32 delay(5) cadence
    buffer_size:    int = 512      # Rolling deque depth (samples)
    welch_nperseg:  int = 128
    welch_noverlap: int = 64

    # ── EEG frequency bands (Hz) ──────────────────────────────────────────────
    delta_low:  float = 1.0
    delta_high: float = 4.0
    theta_low:  float = 4.0
    theta_high: float = 8.0
    alpha_low:  float = 8.0
    alpha_high: float = 12.0
    beta_low:   float = 13.0
    beta_high:  float = 30.0
    gamma_low:  float = 30.0
    gamma_high: float = 45.0

    # ── Adaptive learning ────────────────────────────────────────────────────
    # Warm-up: collect this many seconds of data before enabling adaptive thresh
    warmup_seconds:       float = 90.0
    # Recalculate thresholds every N seconds
    adapt_interval_s:     float = 30.0
    # Exponential forgetting factor for Welford estimator (per sample)
    # 0.995 ≈ half-life ~140 samples (~0.7 s) — fast enough to track drift,
    # slow enough to ignore artifact bursts
    welford_forget:       float = 0.995
    # Clinical z-score multipliers (Shoeb 2009 / Gotman 1982)
    z_brownout:           float = 2.5
    z_blackout:           float = 4.0
    # Hard floor/ceiling so thresholds never go pathologically low or high
    ll_brownout_floor:    float = 300.0   # ADC units, line-length
    ll_blackout_floor:    float = 600.0
    ll_brownout_ceil:     float = 1800.0
    ll_blackout_ceil:     float = 3500.0
    # DAR floors raised: with the relative alpha-floor fix the ratio is now
    # bounded.  Resting EEG DAR is typically 0.5–3; ictal starts around 5–8.
    dar_brownout_floor:   float = 4.0     # delta/alpha ratio
    dar_blackout_floor:   float = 7.0
    hfe_brownout_floor:   float = 0.10    # high-freq energy ratio
    hfe_blackout_floor:   float = 0.18

    # ── Analysis throttle ────────────────────────────────────────────────────
    # Run Welch PSD + state machine only every N valid samples received.
    # At 200 Hz, stride=20 → 10 Hz analysis rate → each confirmation tick ≈ 100 ms.
    # This is the primary defence against sub-second state toggling: the old
    # confirm_ticks=5 at 200 Hz analysis filled in just 25 ms.
    analysis_stride:     int   = 20

    # ── Artifact rejection ───────────────────────────────────────────────────
    # Computed LL values above this ceiling indicate motion artifact or
    # electrode disconnection.  Such epochs skip the state machine AND are
    # NOT fed to the Welford estimator (prevents threshold corruption).
    artifact_ll_ceiling: float = 1500.0

    # ── State machine ─────────────────────────────────────────────────────────
    history_len:         int   = 40
    # At 10 Hz analysis, 50 ticks = 5 s hold before any state can change.
    min_state_hold:      int   = 50
    # Post-ictal minimum hold: 200 ticks × 100 ms = 20 s
    postictal_hold:      int   = 200
    # Consecutive ticks agreeing before a state transition is confirmed.
    # At 10 Hz, 8 ticks = 800 ms — enough to reject a single-sample artifact.
    confirm_ticks:       int   = 8

    # ── DAR cap fed to Welford ────────────────────────────────────────────────
    # The delta/alpha ratio can explode to hundreds when alpha ≈ 0 (movement).
    # Cap the value that enters the estimator so one bad epoch cannot corrupt
    # the adaptive thresholds.  The raw dar is still used for classification.
    dar_welford_cap:     float = 25.0

    # ── Legacy focus/relax thresholds (kept for score-history panel) ──────────
    focus_threshold:     float = 0.030
    relax_threshold:     float = 0.008
    relax_streak_needed: int   = 15

    # ── Mobile / webhook alert ────────────────────────────────────────────────
    # ntfy.sh example:  "https://ntfy.sh/YOUR_TOPIC_NAME"
    # Pushover / any HTTP POST endpoint also works — see send_alert()
    alert_webhook: str = ""   # ← paste your ntfy.sh / webhook URL here

    # ── Session log ───────────────────────────────────────────────────────────
    session_log_path: str = "seizure_session.jsonl"

    # ── ESP32 display mirror ───────────────────────────────────────────────────
    diff_spike_threshold: int = 300   # kept for diff-panel reference line


CFG = Config()


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Online Welford estimator with exponential forgetting
# ─────────────────────────────────────────────────────────────────────────────
class WelfordEWMA:
    """
    Exponentially-weighted online mean + variance estimator.
    Forget factor λ ∈ (0,1): older samples decay by λ per update.
    Equivalent to a window of ~1/(1-λ) samples.
    """
    def __init__(self, forget: float = 0.995):
        self._λ  = forget
        self._w  = 0.0   # effective weight sum
        self._m  = 0.0   # weighted mean
        self._s  = 0.0   # weighted sum-of-squares (for variance)
        self.n   = 0     # raw count

    def update(self, x: float):
        self._w  = self._λ * self._w + 1.0
        old_m    = self._m
        self._m  = old_m + (x - old_m) / self._w
        self._s  = self._λ * self._s + (x - old_m) * (x - self._m)
        self.n  += 1

    @property
    def mean(self) -> float:
        return self._m

    @property
    def std(self) -> float:
        if self._w < 2:
            return 0.0
        return float(np.sqrt(self._s / self._w))

    def threshold(self, z: float) -> float:
        return self.mean + z * self.std


# ─────────────────────────────────────────────────────────────────────────────
# Adaptive threshold manager
# ─────────────────────────────────────────────────────────────────────────────
class AdaptiveThresholds:
    """
    Maintains per-feature Welford estimators and exposes the current
    brownout / blackout thresholds.  Thresholds are frozen during a
    confirmed seizure so the seizure itself does not pollute the baseline.
    """
    def __init__(self):
        self.ll_est  = WelfordEWMA(CFG.welford_forget)   # line-length
        self.dar_est = WelfordEWMA(CFG.welford_forget)   # delta/alpha ratio
        self.hfe_est = WelfordEWMA(CFG.welford_forget)   # high-freq energy ratio

        # Start with literature-derived hard defaults (will adapt within ~90 s)
        self.ll_brownout  = 350.0
        self.ll_blackout  = 700.0
        self.dar_brownout = 2.5
        self.dar_blackout = 4.5
        self.hfe_brownout = 0.10
        self.hfe_blackout = 0.18

        self._frozen      = False        # True during confirmed seizure
        self._last_adapt  = time.time()
        self._start       = time.time()

    @property
    def warmed_up(self) -> bool:
        return (time.time() - self._start) >= CFG.warmup_seconds

    def freeze(self):
        self._frozen = True

    def unfreeze(self):
        self._frozen = False

    def feed(self, ll: float, dar: float, hfe: float):
        """Call once per analysis tick with the three feature values."""
        if self._frozen:
            return
        self.ll_est.update(ll)
        self.dar_est.update(dar)
        self.hfe_est.update(hfe)
        # Recalculate thresholds on interval
        now = time.time()
        if self.warmed_up and (now - self._last_adapt) >= CFG.adapt_interval_s:
            self._recalc()
            self._last_adapt = now

    def _recalc(self):
        raw_ll_b  = self.ll_est.threshold(CFG.z_brownout)
        raw_ll_k  = self.ll_est.threshold(CFG.z_blackout)
        self.ll_brownout = float(np.clip(raw_ll_b,
                                         CFG.ll_brownout_floor,
                                         CFG.ll_brownout_ceil))
        self.ll_blackout = float(np.clip(raw_ll_k,
                                         CFG.ll_blackout_floor,
                                         CFG.ll_blackout_ceil))

        raw_dar_b  = self.dar_est.threshold(CFG.z_brownout)
        raw_dar_k  = self.dar_est.threshold(CFG.z_blackout)
        self.dar_brownout = max(raw_dar_b, CFG.dar_brownout_floor)
        self.dar_blackout = max(raw_dar_k, CFG.dar_blackout_floor)

        raw_hfe_b  = self.hfe_est.threshold(CFG.z_brownout)
        raw_hfe_k  = self.hfe_est.threshold(CFG.z_blackout)
        self.hfe_brownout = max(raw_hfe_b, CFG.hfe_brownout_floor)
        self.hfe_blackout = max(raw_hfe_k, CFG.hfe_blackout_floor)

        log.info(
            "Thresholds updated — "
            "LL: %.0f/%.0f  DAR: %.2f/%.2f  HFE: %.3f/%.3f",
            self.ll_brownout, self.ll_blackout,
            self.dar_brownout, self.dar_blackout,
            self.hfe_brownout, self.hfe_blackout,
        )

    def classify(self, ll: float, dar: float, hfe: float) -> str:
        """Returns 'BLACKOUT', 'BROWNOUT', or 'NORMAL'."""
        blackout_votes = (
            (ll  >= self.ll_blackout)  +
            (dar >= self.dar_blackout) +
            (hfe >= self.hfe_blackout)
        )
        brownout_votes = (
            (ll  >= self.ll_brownout)  +
            (dar >= self.dar_brownout) +
            (hfe >= self.hfe_brownout)
        )
        if blackout_votes >= 2:
            return "BLACKOUT"
        if brownout_votes >= 2:
            return "BROWNOUT"
        return "NORMAL"


ADAPT = AdaptiveThresholds()


# ─────────────────────────────────────────────────────────────────────────────
# Thread-safe shared state
# ─────────────────────────────────────────────────────────────────────────────
class SharedState:
    def __init__(self):
        self._lock           = threading.Lock()
        self.eeg_buf         = deque(maxlen=CFG.buffer_size)
        self.baseline_buf    = deque(maxlen=CFG.buffer_size)
        self.diff_buf        = deque(maxlen=CFG.buffer_size)
        self.score_hist      = deque(maxlen=CFG.history_len)
        self.alpha_ratio     = 0.0
        self.beta_ratio      = 0.0
        self.delta_ratio     = 0.0
        self.gamma_ratio     = 0.0
        self.avg_score       = 0.0
        self.line_length     = 0.0
        self.dar             = 0.0    # delta/alpha ratio
        self.hfe             = 0.0    # high-freq energy ratio
        self.seizure_state   = "NORMAL"   # NORMAL / BROWNOUT / BLACKOUT / POST-ICTAL
        self.state_hold      = 0
        self.state_confirm   = 0
        self.postictal_hold  = 0
        self.relax_streak    = 0
        self.psd_freqs       = None
        self.psd_power       = None
        self.running         = True
        self.warmed_up       = False
        # Fields mirrored directly from the ESP32 firmware (fields 4 & 5)
        self.esp32_state     = 0     # 0=NORMAL 1=BROWNOUT 2=BLACKOUT 3=POST-ICTAL
        self.esp32_thresh    = 80    # current adaptive brownout threshold on MCU
        self.artifact_count  = 0     # cumulative motion artifact epochs skipped
        # Adaptive threshold snapshot for display
        self.thr_ll_b        = ADAPT.ll_brownout
        self.thr_ll_k        = ADAPT.ll_blackout
        self.thr_dar_b       = ADAPT.dar_brownout
        self.thr_dar_k       = ADAPT.dar_blackout
        self.thr_hfe_b       = ADAPT.hfe_brownout
        self.thr_hfe_k       = ADAPT.hfe_blackout

    def update(self, **kwargs):
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def snapshot(self):
        with self._lock:
            return {k: v for k, v in self.__dict__.items()
                    if not k.startswith("_")}


SHARED = SharedState()


# ─────────────────────────────────────────────────────────────────────────────
# Session logger  — writes JSONL for post-session review
# ─────────────────────────────────────────────────────────────────────────────
_log_lock = threading.Lock()

def log_event(event_type: str, **payload):
    record = {
        "ts":    datetime.datetime.now().isoformat(timespec="milliseconds"),
        "event": event_type,
        **payload,
    }
    with _log_lock:
        with open(CFG.session_log_path, "a") as fh:
            fh.write(json.dumps(record) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Mobile / webhook alert  (ntfy.sh, Pushover, custom)
# ─────────────────────────────────────────────────────────────────────────────
def send_alert(title: str, body: str, priority: str = "high"):
    if not CFG.alert_webhook or not _REQUESTS_OK:
        return
    try:
        requests.post(
            CFG.alert_webhook,
            data=body.encode(),
            headers={
                "Title":    title,
                "Priority": priority,
                "Tags":     "rotating_light,brain",
            },
            timeout=4,
        )
        log.info("Alert sent: %s", title)
    except Exception as exc:
        log.warning("Alert failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Serial parser  — handles "eegValue baseline diff state adaptThreshold\n"
#   (5 fields as emitted by seizure_monitor.ino)
#   Lines beginning with '#' are diagnostic comments from the firmware and are
#   intentionally skipped rather than treated as parse failures.
# ─────────────────────────────────────────────────────────────────────────────
def parse_line(raw_bytes: bytes):
    try:
        line = raw_bytes.decode(errors="replace").strip()
        if not line or line.startswith("#"):
            return None                   # firmware comment / blank line
        parts = line.split()
        if len(parts) < 5:
            return None                   # incomplete / malformed packet
        return (
            float(parts[0]),              # eegValue      (ADC 0–4095)
            float(parts[1]),              # baseline      (EMA float)
            float(parts[2]),              # diff          (|eeg − baseline|)
            int(parts[3]),                # state         (0=NORMAL…3=POST-ICTAL)
            int(parts[4]),                # adaptThreshold (brownout threshold)
        )
    except (ValueError, AttributeError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Signal feature extraction
# ─────────────────────────────────────────────────────────────────────────────
def band_power(freqs: np.ndarray, psd: np.ndarray,
               low: float, high: float) -> float:
    mask = (freqs >= low) & (freqs <= high)
    if not np.any(mask):
        return 0.0
    return float(_trapz(psd[mask], freqs[mask]))


def compute_line_length(samples: np.ndarray) -> float:
    """
    Gotman (1982) line-length detector — sum of |x[n] - x[n-1]|.
    Normalised per sample so buffer-size changes don't shift the threshold.
    """
    if len(samples) < 2:
        return 0.0
    return float(np.sum(np.abs(np.diff(samples))) / len(samples))


def analyse(samples: np.ndarray):
    """
    Returns (alpha_r, beta_r, delta_r, gamma_r, ll, dar, hfe, freqs, psd).
    ll  = normalised line-length (Gotman seizure detector)
    dar = delta/alpha power ratio (hallmark of ictal activity)
    hfe = gamma band energy ratio (high-freq energy, post-ictal marker)
    """
    samples = samples - np.mean(samples)   # remove DC offset

    freqs, psd = welch(
        samples,
        fs=CFG.sample_rate,
        window="hann",
        nperseg=CFG.welch_nperseg,
        noverlap=CFG.welch_noverlap,
        scaling="density",
    )

    delta = band_power(freqs, psd, CFG.delta_low, CFG.delta_high)
    alpha = band_power(freqs, psd, CFG.alpha_low,  CFG.alpha_high)
    beta  = band_power(freqs, psd, CFG.beta_low,   CFG.beta_high)
    gamma = band_power(freqs, psd, CFG.gamma_low,  CFG.gamma_high)
    total = band_power(freqs, psd, 1.0, 45.0)

    if total < 1e-12:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, freqs, psd

    alpha_r = alpha / total
    beta_r  = beta  / total
    delta_r = delta / total
    gamma_r = gamma / total

    # Seizure features
    # DAR: use a relative alpha floor (2 % of total power) instead of 1e-12.
    # This prevents DAR from exploding to hundreds when alpha ≈ 0 due to
    # movement or electrode dropout — the most common source of false alarms.
    alpha_floor = max(alpha, total * 0.02)
    dar = delta / alpha_floor               # delta:alpha ratio
    hfe = gamma / max(total - gamma, 1e-12)  # high-freq energy fraction
    ll  = compute_line_length(samples) * 10.0  # scaled to ADC-unit range

    return alpha_r, beta_r, delta_r, gamma_r, ll, dar, hfe, freqs, psd


# ─────────────────────────────────────────────────────────────────────────────
# Seizure state machine
# ─────────────────────────────────────────────────────────────────────────────
_prev_seizure_state = "NORMAL"
_confirm_buf: deque = deque(maxlen=CFG.confirm_ticks)

def update_seizure_state(raw_class: str, alpha_r: float, beta_r: float,
                          ll: float, dar: float, hfe: float) -> str:
    """
    Hysteresis + confirmation filter on top of the raw classifier output.
    States: NORMAL → BROWNOUT → BLACKOUT → POST-ICTAL → NORMAL
    """
    global _prev_seizure_state

    _confirm_buf.append(raw_class)
    # Confirm only if the last N ticks agree (prevents single-sample spikes)
    if len(_confirm_buf) < CFG.confirm_ticks:
        confirmed = _prev_seizure_state
    else:
        counts = {s: _confirm_buf.count(s) for s in ("BLACKOUT", "BROWNOUT", "NORMAL")}
        if counts["BLACKOUT"] >= CFG.confirm_ticks - 1:
            confirmed = "BLACKOUT"
        elif counts["BROWNOUT"] >= CFG.confirm_ticks - 1:
            confirmed = "BROWNOUT"
        else:
            confirmed = "NORMAL"

    current = _prev_seizure_state
    postictal_hold = SHARED.postictal_hold

    # Post-ictal hold: cannot return to NORMAL too quickly
    if current == "POST-ICTAL":
        if postictal_hold > 0:
            SHARED.update(postictal_hold=postictal_hold - 1)
            return "POST-ICTAL"
        else:
            if confirmed == "NORMAL":
                new_state = "NORMAL"
            else:
                new_state = confirmed
    elif current == "BLACKOUT":
        ADAPT.freeze()
        if confirmed != "BLACKOUT":
            # Transition to post-ictal
            new_state = "POST-ICTAL"
            SHARED.update(postictal_hold=CFG.postictal_hold)
            ADAPT.unfreeze()
            _on_state_change("BLACKOUT", "POST-ICTAL", ll, dar, hfe)
        else:
            new_state = "BLACKOUT"
    elif current == "BROWNOUT":
        if confirmed == "BLACKOUT":
            new_state = "BLACKOUT"
            _on_state_change("BROWNOUT", "BLACKOUT", ll, dar, hfe)
        elif confirmed == "NORMAL":
            new_state = "NORMAL"
            _on_state_change("BROWNOUT", "NORMAL", ll, dar, hfe)
        else:
            new_state = "BROWNOUT"
    else:  # NORMAL
        ADAPT.unfreeze()
        if confirmed == "BLACKOUT":
            new_state = "BLACKOUT"
            _on_state_change("NORMAL", "BLACKOUT", ll, dar, hfe)
        elif confirmed == "BROWNOUT":
            new_state = "BROWNOUT"
            _on_state_change("NORMAL", "BROWNOUT", ll, dar, hfe)
        else:
            new_state = "NORMAL"

    _prev_seizure_state = new_state

    # Score history (β−α used for focus panel, kept for continuity)
    score = beta_r - alpha_r
    SHARED.score_hist.append(score)
    avg = float(np.mean(SHARED.score_hist))
    SHARED.update(avg_score=avg)

    return new_state


def _on_state_change(from_s: str, to_s: str, ll: float, dar: float, hfe: float):
    log.warning("STATE  %s → %s   LL=%.1f  DAR=%.2f  HFE=%.3f",
                from_s, to_s, ll, dar, hfe)
    log_event("state_change", from_state=from_s, to_state=to_s,
              ll=round(ll, 2), dar=round(dar, 3), hfe=round(hfe, 4))
    if to_s == "BROWNOUT":
        threading.Thread(target=send_alert,
                         args=("⚠ Brownout — Pre-ictal Warning",
                               "Pre-ictal EEG activity detected. "
                               "Monitor patient closely.  "
                               f"LL={ll:.0f}  DAR={dar:.2f}"),
                         daemon=True).start()
    elif to_s == "BLACKOUT":
        threading.Thread(target=send_alert,
                         args=("🚨 BLACKOUT — Seizure Detected",
                               "Active seizure detected!  "
                               "Immediate attention required.  "
                               f"LL={ll:.0f}  DAR={dar:.2f}  HFE={hfe:.3f}"),
                         kwargs={"priority": "urgent"},
                         daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# Serial reader thread
# ─────────────────────────────────────────────────────────────────────────────
def serial_reader(ser: serial.Serial) -> None:
    log.info("Serial reader started on %s", CFG.port)

    _stride_counter = 0   # counts valid samples; analysis fires every stride

    while SHARED.running:
        try:
            raw = ser.readline()
            if not raw:
                continue
        except serial.SerialException as exc:
            log.error("Serial error: %s", exc)
            SHARED.update(running=False)
            break

        parsed = parse_line(raw)
        if parsed is None:
            continue

        eeg_val, baseline_val, diff_val, esp32_state, esp32_thresh = parsed
        SHARED.eeg_buf.append(eeg_val)
        SHARED.baseline_buf.append(baseline_val)
        SHARED.diff_buf.append(diff_val)
        # Mirror the MCU's own state + adaptive threshold for the status panel
        SHARED.update(esp32_state=esp32_state, esp32_thresh=esp32_thresh)

        # ── Analysis throttle ─────────────────────────────────────────────
        # Run the expensive Welch PSD + state machine only every
        # analysis_stride samples (default 20 → 10 Hz), not at 200 Hz.
        # This is the primary fix for the sub-second state toggling.
        _stride_counter += 1
        if _stride_counter < CFG.analysis_stride:
            continue
        _stride_counter = 0

        if len(SHARED.eeg_buf) < CFG.buffer_size:
            continue

        samples = np.array(SHARED.eeg_buf)
        (alpha_r, beta_r, delta_r, gamma_r,
         ll, dar, hfe, freqs, psd) = analyse(samples)

        # ── Artifact rejection ────────────────────────────────────────────
        # An LL above the ceiling means motion artifact or electrode
        # disconnection — skip state machine AND Welford update to prevent
        # threshold corruption.
        if ll > CFG.artifact_ll_ceiling:
            log.debug("Artifact epoch skipped  LL=%.0f > ceiling=%.0f",
                      ll, CFG.artifact_ll_ceiling)
            with SHARED._lock:
                SHARED.artifact_count += 1
            SHARED.update(
                alpha_ratio  = alpha_r,
                beta_ratio   = beta_r,
                delta_ratio  = delta_r,
                gamma_ratio  = gamma_r,
                line_length  = ll,
                dar          = dar,
                hfe          = hfe,
                psd_freqs    = freqs,
                psd_power    = psd,
            )
            continue

        # ── Feed adaptive model (cap DAR to protect Welford estimator) ────
        # The DAR can spike to 100+ when alpha ≈ 0 even after the relative
        # floor fix (e.g., if delta itself is very large).  Cap what enters
        # the estimator so one noisy epoch cannot corrupt the thresholds.
        ADAPT.feed(ll, min(dar, CFG.dar_welford_cap), hfe)

        raw_class = ADAPT.classify(ll, dar, hfe)
        new_state = update_seizure_state(raw_class, alpha_r, beta_r, ll, dar, hfe)

        SHARED.update(
            alpha_ratio   = alpha_r,
            beta_ratio    = beta_r,
            delta_ratio   = delta_r,
            gamma_ratio   = gamma_r,
            line_length   = ll,
            dar           = dar,
            hfe           = hfe,
            psd_freqs     = freqs,
            psd_power     = psd,
            seizure_state = new_state,
            warmed_up     = ADAPT.warmed_up,
            thr_ll_b      = ADAPT.ll_brownout,
            thr_ll_k      = ADAPT.ll_blackout,
            thr_dar_b     = ADAPT.dar_brownout,
            thr_dar_k     = ADAPT.dar_blackout,
            thr_hfe_b     = ADAPT.hfe_brownout,
            thr_hfe_k     = ADAPT.hfe_blackout,
        )

        log.debug(
            "α=%.3f β=%.3f δ=%.3f LL=%.1f DAR=%.2f HFE=%.3f → %s",
            alpha_r, beta_r, delta_r, ll, dar, hfe, new_state,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Plot theme
# ─────────────────────────────────────────────────────────────────────────────
BG        = "#0d0d0d"
PANEL     = "#141414"
BORDER    = "#252525"
TEXT_PRI  = "#e0e0e0"
TEXT_SEC  = "#777777"
COL_EEG   = "#4fc3f7"
COL_BASE  = "#f9a825"
COL_DIFF  = "#ef5350"
COL_DELTA = "#ce93d8"
COL_ALP   = "#4fc3f7"
COL_BET   = "#ff8a65"
COL_PSD   = "#80cbc4"
COL_GRID  = "#1a1a1a"

STATE_COLORS = {
    "NORMAL":     "#4caf50",
    "BROWNOUT":   "#ffab00",
    "BLACKOUT":   "#ff5252",
    "POST-ICTAL": "#b0bec5",
}
STATE_ICONS = {
    "NORMAL":     "◉",
    "BROWNOUT":   "⚠",
    "BLACKOUT":   "✖",
    "POST-ICTAL": "◌",
}


def _style_ax(ax):
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=TEXT_SEC, labelsize=8)
    ax.yaxis.label.set_color(TEXT_SEC)
    ax.xaxis.label.set_color(TEXT_SEC)
    ax.title.set_color(TEXT_PRI)
    for spine in ax.spines.values():
        spine.set_edgecolor(BORDER)
    ax.grid(color=COL_GRID, linewidth=0.4, linestyle="--", alpha=0.7)


# ─────────────────────────────────────────────────────────────────────────────
# Figure layout
# ─────────────────────────────────────────────────────────────────────────────
def build_figure():
    fig = plt.figure(figsize=(16, 9), facecolor=BG)
    fig.canvas.manager.set_window_title("Epilepsy Seizure Monitor — Live EEG")

    # 5 rows × 4 columns
    gs = gridspec.GridSpec(
        5, 4, figure=fig,
        hspace=0.62, wspace=0.38,
        left=0.05, right=0.97,
        top=0.93, bottom=0.06,
    )

    ax_eeg    = fig.add_subplot(gs[0, :3])   # raw EEG + baseline (wide)
    ax_state  = fig.add_subplot(gs[0:2, 3])  # seizure state indicator (tall)
    ax_diff   = fig.add_subplot(gs[1, :3])   # diff signal
    ax_psd    = fig.add_subplot(gs[2, :2])   # Welch PSD
    ax_bar    = fig.add_subplot(gs[2, 2])    # band-power bars
    ax_thresh = fig.add_subplot(gs[2, 3])    # adaptive threshold display
    ax_hist   = fig.add_subplot(gs[3, :3])   # β−α score history
    ax_ll     = fig.add_subplot(gs[3, 3])    # line-length gauge
    ax_dar    = fig.add_subplot(gs[4, :2])   # delta/alpha ratio trend
    ax_hfe    = fig.add_subplot(gs[4, 2])    # high-freq energy trend
    ax_warn   = fig.add_subplot(gs[4, 3])    # warm-up / model status

    axes_all = [ax_eeg, ax_state, ax_diff, ax_psd, ax_bar, ax_thresh,
                ax_hist, ax_ll, ax_dar, ax_hfe, ax_warn]
    for ax in axes_all:
        _style_ax(ax)

    # Clear tick-less panels
    for ax in (ax_state, ax_thresh, ax_ll, ax_warn):
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)

    fig.text(0.5, 0.965,
             "EEG Epilepsy Seizure Monitor — Real-Time Analysis",
             ha="center", color=TEXT_PRI, fontsize=13, fontweight="500")

    return (fig, ax_eeg, ax_diff, ax_psd, ax_bar, ax_hist,
            ax_state, ax_thresh, ax_ll, ax_dar, ax_hfe, ax_warn)


# ─────────────────────────────────────────────────────────────────────────────
# Animation
# ─────────────────────────────────────────────────────────────────────────────
def make_animator(fig, ax_eeg, ax_diff, ax_psd, ax_bar, ax_hist,
                  ax_state, ax_thresh, ax_ll, ax_dar, ax_hfe, ax_warn):

    score_history = []
    ll_history    = []
    dar_history   = []
    hfe_history   = []

    def update(_frame):
        snap          = SHARED.snapshot()
        eeg_buf       = snap["eeg_buf"]
        base_buf      = snap["baseline_buf"]
        diff_buf      = snap["diff_buf"]
        alpha_r       = snap["alpha_ratio"]
        beta_r        = snap["beta_ratio"]
        delta_r       = snap["delta_ratio"]
        gamma_r       = snap["gamma_ratio"]
        avg_score     = snap["avg_score"]
        sz_state      = snap["seizure_state"]
        ll            = snap["line_length"]
        dar           = snap["dar"]
        hfe           = snap["hfe"]
        freqs         = snap["psd_freqs"]
        psd           = snap["psd_power"]
        warmed_up     = snap["warmed_up"]
        thr_ll_b      = snap["thr_ll_b"]
        thr_ll_k      = snap["thr_ll_k"]
        thr_dar_b     = snap["thr_dar_b"]
        thr_dar_k     = snap["thr_dar_k"]
        thr_hfe_b     = snap["thr_hfe_b"]
        thr_hfe_k     = snap["thr_hfe_k"]

        sc = STATE_COLORS.get(sz_state, TEXT_SEC)
        xs_eeg  = np.arange(len(eeg_buf))
        xs_diff = np.arange(len(diff_buf))

        # Rolling history buffers
        def _push(hist, val, maxlen=200):
            hist.append(val)
            if len(hist) > maxlen:
                hist.pop(0)

        _push(score_history, avg_score)
        _push(ll_history,    ll)
        _push(dar_history,   dar)
        _push(hfe_history,   hfe)

        # ── Raw EEG + Baseline ────────────────────────────────────────────────
        ax_eeg.cla(); _style_ax(ax_eeg)
        if eeg_buf:
            # Tint background by seizure state
            if sz_state == "BLACKOUT":
                ax_eeg.set_facecolor("#1a0000")
            elif sz_state == "BROWNOUT":
                ax_eeg.set_facecolor("#1a1000")

            ax_eeg.plot(xs_eeg, eeg_buf,  color=COL_EEG,  lw=0.7, label="EEG raw", alpha=0.9)
            ax_eeg.plot(xs_eeg, base_buf, color=COL_BASE, lw=1.1, label="Baseline",
                        alpha=0.85, linestyle="--")
            ax_eeg.set_xlim(0, len(eeg_buf))
            ax_eeg.legend(fontsize=7, labelcolor=TEXT_SEC,
                          facecolor=PANEL, edgecolor=BORDER, loc="upper right")
        ax_eeg.set_title("Raw EEG Signal + ESP32 Adaptive Baseline", fontsize=9, pad=4)
        ax_eeg.set_ylabel("ADC Value", fontsize=8)

        # ── Diff signal ────────────────────────────────────────────────────────
        ax_diff.cla(); _style_ax(ax_diff)
        if diff_buf:
            diff_arr = np.array(diff_buf)
            ax_diff.plot(xs_diff, diff_arr, color=COL_DIFF, lw=0.7, alpha=0.85)

            ax_diff.axhline(
                CFG.diff_spike_threshold,
                color="#ff5252",
                lw=0.8,
                linestyle="--",
                alpha=0.7,
                label=f"Spike ref ({CFG.diff_spike_threshold})"
            )

            ax_diff.fill_between(
                xs_diff,
                CFG.diff_spike_threshold,
                diff_arr,
                where=diff_arr >= CFG.diff_spike_threshold,
                color="#ff5252",
                alpha=0.20,
                interpolate=True
            )
            ax_diff.set_xlim(0, len(xs_diff))
            ax_diff.legend(fontsize=7, labelcolor=TEXT_SEC,
                           facecolor=PANEL, edgecolor=BORDER)
        ax_diff.set_title("Diff |eeg − baseline| (spike detector)", fontsize=9, pad=4)
        ax_diff.set_ylabel("Amplitude", fontsize=8)

        # ── Welch PSD ──────────────────────────────────────────────────────────
        ax_psd.cla(); _style_ax(ax_psd)
        if freqs is not None:
            ax_psd.semilogy(freqs, psd + 1e-12, color=COL_PSD, lw=0.9)
            ax_psd.set_xlim(0, 50)
            ax_psd.axvspan(CFG.delta_low, CFG.delta_high, alpha=0.10,
                           color=COL_DELTA, label="δ 1–4 Hz")
            ax_psd.axvspan(CFG.alpha_low, CFG.alpha_high, alpha=0.10,
                           color=COL_ALP,   label="α 8–12 Hz")
            ax_psd.axvspan(CFG.beta_low,  CFG.beta_high,  alpha=0.10,
                           color=COL_BET,   label="β 13–30 Hz")
            ax_psd.legend(fontsize=7, labelcolor=TEXT_SEC,
                          facecolor=PANEL, edgecolor=BORDER, loc="upper right")
        ax_psd.set_title("Welch Power Spectral Density", fontsize=9, pad=4)
        ax_psd.set_xlabel("Frequency (Hz)", fontsize=8)
        ax_psd.set_ylabel("Power (log)", fontsize=8)

        # ── Band-power bars ────────────────────────────────────────────────────
        ax_bar.cla(); _style_ax(ax_bar)
        labels = ["δ\n1–4", "α\n8–12", "β\n13–30", "γ\n30–45"]
        vals   = [delta_r, alpha_r, beta_r, gamma_r]
        colors = [COL_DELTA, COL_ALP, COL_BET, "#ffcc80"]
        bars = ax_bar.bar(labels, vals, color=colors, width=0.5, edgecolor=BORDER)
        top  = max(max(vals, default=0.01), 0.01) * 1.5
        ax_bar.set_ylim(0, top)
        ax_bar.set_title("Band Power", fontsize=9, pad=4)
        ax_bar.set_ylabel("Rel. power", fontsize=8)
        for bar, val in zip(bars, vals):
            ax_bar.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + top * 0.03,
                        f"{val:.3f}", ha="center", va="bottom",
                        color=TEXT_PRI, fontsize=8)

        # ── Adaptive threshold display ─────────────────────────────────────────
        ax_thresh.cla()
        ax_thresh.set_facecolor(PANEL)
        ax_thresh.set_xticks([]); ax_thresh.set_yticks([])
        for s in ax_thresh.spines.values():
            s.set_edgecolor(BORDER); s.set_visible(True)
        rows = [
            ("Line-length", thr_ll_b,  thr_ll_k,  f"{ll:.0f}"),
            ("δ/α ratio",  thr_dar_b, thr_dar_k, f"{dar:.2f}"),
            ("HF energy",  thr_hfe_b, thr_hfe_k, f"{hfe:.3f}"),
        ]
        ax_thresh.text(0.5, 0.96, "Adaptive Thresholds",
                       ha="center", va="top", color=TEXT_PRI, fontsize=8,
                       transform=ax_thresh.transAxes)
        ax_thresh.text(0.05, 0.86, "Feature", color=TEXT_SEC, fontsize=7,
                       transform=ax_thresh.transAxes)
        ax_thresh.text(0.48, 0.86, "Warn", color="#ffab00", fontsize=7,
                       transform=ax_thresh.transAxes)
        ax_thresh.text(0.66, 0.86, "Alarm", color="#ff5252", fontsize=7,
                       transform=ax_thresh.transAxes)
        ax_thresh.text(0.84, 0.86, "Now", color=TEXT_PRI, fontsize=7,
                       transform=ax_thresh.transAxes)
        for i, (name, wb, kb, cur) in enumerate(rows):
            y = 0.72 - i * 0.22
            ax_thresh.text(0.05, y, name, color=TEXT_SEC, fontsize=7,
                           transform=ax_thresh.transAxes)
            ax_thresh.text(0.48, y, f"{wb:.1f}", color="#ffab00", fontsize=7,
                           transform=ax_thresh.transAxes)
            ax_thresh.text(0.66, y, f"{kb:.1f}", color="#ff5252", fontsize=7,
                           transform=ax_thresh.transAxes)
            ax_thresh.text(0.84, y, cur, color=TEXT_PRI, fontsize=7,
                           transform=ax_thresh.transAxes)
        warm_txt = "✓ adaptive" if warmed_up else f"warm-up…"
        warm_col = "#4caf50" if warmed_up else "#ffab00"
        ax_thresh.text(0.5, 0.04, warm_txt, ha="center", va="bottom",
                       color=warm_col, fontsize=7,
                       transform=ax_thresh.transAxes)

        # ── β−α score history ─────────────────────────────────────────────────
        ax_hist.cla(); _style_ax(ax_hist)
        if len(score_history) > 1:
            hs = np.arange(len(score_history))
            ys = np.array(score_history)
            ax_hist.fill_between(hs, 0, ys, where=ys >= 0,
                                 color="#69f0ae", alpha=0.20, interpolate=True)
            ax_hist.fill_between(hs, 0, ys, where=ys < 0,
                                 color="#ff7043", alpha=0.20, interpolate=True)
            ax_hist.plot(hs, ys, color=TEXT_SEC, lw=0.8)
            ax_hist.axhline(CFG.focus_threshold, color="#69f0ae", lw=0.7,
                            linestyle="--", alpha=0.8)
            ax_hist.axhline(CFG.relax_threshold, color="#ff7043", lw=0.7,
                            linestyle="--", alpha=0.8)
            ax_hist.axhline(0, color=BORDER, lw=0.5)
            ax_hist.set_xlim(0, max(len(score_history) - 1, 1))
        ax_hist.set_title("β−α Score History", fontsize=9, pad=4)
        ax_hist.set_xlabel("Update ticks", fontsize=8)
        ax_hist.set_ylabel("β − α ratio", fontsize=8)

        # ── Line-length gauge (rolling) ───────────────────────────────────────
        ax_ll.cla(); _style_ax(ax_ll)
        if len(ll_history) > 1:
            lx = np.arange(len(ll_history))
            ly = np.array(ll_history)
            ax_ll.plot(lx, ly, color="#80cbc4", lw=0.8)
            ax_ll.axhline(thr_ll_b, color="#ffab00", lw=0.8, linestyle="--",
                          alpha=0.8, label=f"Warn {thr_ll_b:.0f}")
            ax_ll.axhline(thr_ll_k, color="#ff5252", lw=0.8, linestyle="--",
                          alpha=0.8, label=f"Alarm {thr_ll_k:.0f}")
            ax_ll.fill_between(lx, thr_ll_b, ly,
                               where=ly >= thr_ll_b,
                               color="#ffab00", alpha=0.18, interpolate=True)
            ax_ll.fill_between(lx, thr_ll_k, ly,
                               where=ly >= thr_ll_k,
                               color="#ff5252", alpha=0.25, interpolate=True)
            ax_ll.set_xlim(0, max(len(ll_history) - 1, 1))
            ax_ll.legend(fontsize=6, labelcolor=TEXT_SEC,
                         facecolor=PANEL, edgecolor=BORDER, loc="upper left")
        ax_ll.set_title("Line-Length (Gotman)", fontsize=9, pad=4)
        ax_ll.set_ylabel("LL (norm.)", fontsize=8)

        # ── δ/α ratio trend ───────────────────────────────────────────────────
        ax_dar.cla(); _style_ax(ax_dar)
        if len(dar_history) > 1:
            dx2 = np.arange(len(dar_history))
            dy  = np.array(dar_history)
            ax_dar.plot(dx2, dy, color=COL_DELTA, lw=0.8)
            ax_dar.axhline(thr_dar_b, color="#ffab00", lw=0.8,
                           linestyle="--", alpha=0.8,
                           label=f"Warn {thr_dar_b:.2f}")
            ax_dar.axhline(thr_dar_k, color="#ff5252", lw=0.8,
                           linestyle="--", alpha=0.8,
                           label=f"Alarm {thr_dar_k:.2f}")
            ax_dar.fill_between(dx2, thr_dar_b, dy,
                                where=dy >= thr_dar_b,
                                color="#ffab00", alpha=0.18, interpolate=True)
            ax_dar.fill_between(dx2, thr_dar_k, dy,
                                where=dy >= thr_dar_k,
                                color="#ff5252", alpha=0.25, interpolate=True)
            ax_dar.set_xlim(0, max(len(dar_history) - 1, 1))
            ax_dar.legend(fontsize=6, labelcolor=TEXT_SEC,
                          facecolor=PANEL, edgecolor=BORDER, loc="upper left")
        ax_dar.set_title("δ/α Ratio (ictal marker)", fontsize=9, pad=4)
        ax_dar.set_xlabel("Ticks", fontsize=8)
        ax_dar.set_ylabel("Ratio", fontsize=8)

        # ── High-freq energy trend ────────────────────────────────────────────
        ax_hfe.cla(); _style_ax(ax_hfe)
        if len(hfe_history) > 1:
            hx = np.arange(len(hfe_history))
            hy = np.array(hfe_history)
            ax_hfe.plot(hx, hy, color="#ffcc80", lw=0.8)
            ax_hfe.axhline(thr_hfe_b, color="#ffab00", lw=0.8,
                           linestyle="--", alpha=0.8,
                           label=f"Warn {thr_hfe_b:.3f}")
            ax_hfe.axhline(thr_hfe_k, color="#ff5252", lw=0.8,
                           linestyle="--", alpha=0.8,
                           label=f"Alarm {thr_hfe_k:.3f}")
            ax_hfe.fill_between(hx, thr_hfe_b, hy,
                                where=hy >= thr_hfe_b,
                                color="#ffab00", alpha=0.18, interpolate=True)
            ax_hfe.fill_between(hx, thr_hfe_k, hy,
                                where=hy >= thr_hfe_k,
                                color="#ff5252", alpha=0.25, interpolate=True)
            ax_hfe.set_xlim(0, max(len(hfe_history) - 1, 1))
            ax_hfe.legend(fontsize=6, labelcolor=TEXT_SEC,
                          facecolor=PANEL, edgecolor=BORDER, loc="upper left")
        ax_hfe.set_title("High-Freq Energy (γ band)", fontsize=9, pad=4)
        ax_hfe.set_xlabel("Ticks", fontsize=8)
        ax_hfe.set_ylabel("HFE ratio", fontsize=8)

        # ── Seizure state indicator ────────────────────────────────────────────
        ax_state.cla()
        ax_state.set_facecolor("#0d0000" if sz_state == "BLACKOUT" else
                               "#0d0800" if sz_state == "BROWNOUT" else PANEL)
        ax_state.set_xticks([]); ax_state.set_yticks([])
        for s in ax_state.spines.values():
            s.set_edgecolor(sc)
            s.set_linewidth(2.0 if sz_state != "NORMAL" else 0.8)
            s.set_visible(True)

        icon = STATE_ICONS.get(sz_state, "·")
        ax_state.text(0.5, 0.70, icon,
                      ha="center", va="center", color=sc, fontsize=40,
                      transform=ax_state.transAxes)
        ax_state.text(0.5, 0.50, sz_state,
                      ha="center", va="center", color=sc, fontsize=15,
                      fontweight="500", transform=ax_state.transAxes)
        ax_state.text(0.5, 0.38, f"score {avg_score:+.4f}",
                      ha="center", va="center", color=TEXT_SEC, fontsize=8,
                      transform=ax_state.transAxes)
        ax_state.text(0.5, 0.28, f"LL {ll:.0f}  DAR {dar:.2f}",
                      ha="center", va="center", color=TEXT_SEC, fontsize=7,
                      transform=ax_state.transAxes)
        ax_state.text(0.5, 0.18, f"HFE {hfe:.3f}",
                      ha="center", va="center", color=TEXT_SEC, fontsize=7,
                      transform=ax_state.transAxes)
        ax_state.text(0.5, 0.06, "ESP32 · adaptive model",
                      ha="center", va="center", color=TEXT_SEC, fontsize=6,
                      alpha=0.5, transform=ax_state.transAxes)

        # ── Model status panel ─────────────────────────────────────────────────
        ax_warn.cla()
        ax_warn.set_facecolor(PANEL)
        ax_warn.set_xticks([]); ax_warn.set_yticks([])
        for s in ax_warn.spines.values():
            s.set_edgecolor(BORDER); s.set_visible(True)

        status_lines = [
            ("Model",    "Online" if warmed_up else "Warming up", "#4caf50" if warmed_up else "#ffab00"),
            ("Frozen",   "Yes" if ADAPT._frozen else "No",
             "#ff5252" if ADAPT._frozen else "#4caf50"),
            ("Samples",  f"{ADAPT.ll_est.n}",  TEXT_SEC),
            ("LL σ",     f"{ADAPT.ll_est.std:.1f}", TEXT_SEC),
            ("DAR σ",    f"{ADAPT.dar_est.std:.3f}", TEXT_SEC),
            ("MCU state", ["NORM","BRWN","BLCK","POST"][snap.get("esp32_state", 0)],
             ["#4caf50","#ffab00","#ff5252","#b0bec5"][snap.get("esp32_state", 0)]),
            ("MCU thr",  f"{snap.get('esp32_thresh', 0)}", TEXT_SEC),
            ("Artifacts", f"{snap.get('artifact_count', 0)}",
             "#ff5252" if snap.get("artifact_count", 0) > 5 else TEXT_SEC),
        ]
        ax_warn.text(0.5, 0.96, "Model Status", ha="center", va="top",
                     color=TEXT_PRI, fontsize=8, transform=ax_warn.transAxes)
        for i, (k, v, c) in enumerate(status_lines):
            y = 0.80 - i * 0.10
            ax_warn.text(0.1,  y, k, color=TEXT_SEC, fontsize=7,
                         transform=ax_warn.transAxes)
            ax_warn.text(0.62, y, v, color=c, fontsize=7,
                         transform=ax_warn.transAxes)

        return []

    return update


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    log_event("session_start",
              port=CFG.port,
              sample_rate=CFG.sample_rate,
              warmup_s=CFG.warmup_seconds)

    try:
        ser = serial.Serial(CFG.port, CFG.baud_rate, timeout=2)
        log.info("Opened %s @ %d baud", CFG.port, CFG.baud_rate)
    except serial.SerialException as exc:
        log.error("Cannot open %s: %s", CFG.port, exc)
        sys.exit(1)

    reader_thread = threading.Thread(
        target=serial_reader, args=(ser,), daemon=True, name="serial-reader"
    )
    reader_thread.start()

    axes = build_figure()
    fig  = axes[0]
    update_fn = make_animator(*axes)

    ani = animation.FuncAnimation(
        fig, update_fn,
        interval=100,
        blit=False,
        cache_frame_data=False,
    )

    log.info("Live plot open. Close window or Ctrl-C to quit.")
    log.info("Session log → %s", CFG.session_log_path)
    if CFG.alert_webhook:
        log.info("Mobile alerts → %s", CFG.alert_webhook)
    else:
        log.info("Mobile alerts disabled (set CFG.alert_webhook to enable)")

    try:
        plt.show()
    except KeyboardInterrupt:
        pass
    finally:
        SHARED.update(running=False)
        reader_thread.join(timeout=2)
        ser.close()
        log_event("session_end")
        log.info("Serial port closed.  Session log saved.")

    _ = ani   # keep FuncAnimation alive until plt.show() returns


if __name__ == "__main__":
    main()
