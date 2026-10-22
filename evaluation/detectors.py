"""
Offline replay of Vera's two detectors.

1. `run_python_detector` drives the *unmodified* seizure_monitor.py through its
   own `serial_reader()` loop: a fake serial port emits the firmware's
   "eeg baseline diff state thr" lines and a simulated clock advances 5 ms per
   line, so warm-up / re-adaptation timing is exactly what it would be live.
   Only I/O side-effects (alerts, JSONL log, plotting backend) are stubbed.

2. `run_firmware_detector` is a line-by-line port of loop() in
   seizure_monitor_esp32_firmware.ino (EMA baseline, |x-baseline| diff, Welford
   EWMA, adaptive μ+Kσ thresholds, confirm counters, post-ictal hold), JIT
   compiled with numba.  C integer casts/truncation are reproduced.

Both return a per-tick state trace: (times_s, states) with states coded
0=NORMAL 1=BROWNOUT 2=BLACKOUT 3=POST-ICTAL.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path

import numpy as np
from numba import njit

STATE_CODE = {"NORMAL": 0, "BROWNOUT": 1, "BLACKOUT": 2, "POST-ICTAL": 3}
FS = 200.0
DT = 1.0 / FS


# ═════════════════════════════════════════════════════════════════════════════
#  Python analyzer (seizure_monitor.py) — unmodified module, replayed
# ═════════════════════════════════════════════════════════════════════════════
class _SimClock:
    def __init__(self):
        self.t = 1_000_000.0

    def time(self):
        return self.t

    def sleep(self, _):
        pass

    def __getattr__(self, item):            # monotonic, perf_counter, …
        import time as _t
        return getattr(_t, item)


def _ensure_serial_module():
    """seizure_monitor.py imports pyserial; replay never opens a port, so a stub suffices."""
    try:
        import serial  # noqa: F401
    except ImportError:
        stub = types.ModuleType("serial")

        class SerialException(Exception):
            pass

        class Serial:  # pragma: no cover - never instantiated during replay
            def __init__(self, *a, **k):
                raise SerialException("pyserial stub: no real ports in offline replay")

        stub.Serial, stub.SerialException = Serial, SerialException
        sys.modules["serial"] = stub


def load_monitor_module(path: Path):
    _ensure_serial_module()
    import matplotlib
    matplotlib.use = lambda *a, **k: None   # TkAgg not needed headless
    matplotlib.rcParams["backend"] = "Agg"
    spec = importlib.util.spec_from_file_location("seizure_monitor", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["seizure_monitor"] = mod
    spec.loader.exec_module(mod)
    logging.getLogger(mod.__name__).setLevel(logging.ERROR)
    logging.getLogger().setLevel(logging.ERROR)
    mod.log_event = lambda *a, **k: None
    mod.send_alert = lambda *a, **k: None
    return mod


class _FakeSerial:
    """Emits firmware-format serial lines and advances the simulated clock."""

    def __init__(self, mod, clock, adc, fw_baseline, fw_diff, fw_state, fw_thr):
        self.mod, self.clock = mod, clock
        self.adc, self.base, self.diff = adc, fw_baseline, fw_diff
        self.state, self.thr = fw_state, fw_thr
        self.i, self.n = 0, len(adc)

    def readline(self):
        if self.i >= self.n:
            self.mod.SHARED.running = False
            return b""
        i = self.i
        self.i += 1
        self.clock.t += DT
        return (f"{self.adc[i]} {self.base[i]:.2f} {self.diff[i]} "
                f"{self.state[i]} {self.thr[i]}\n").encode()


def run_python_detector(mod, adc, fw_trace, cfg_overrides=None):
    """Replay one recording through seizure_monitor.serial_reader()."""
    from collections import deque

    clock = _SimClock()
    mod.time = clock                                   # module-level `time`
    mod.CFG = mod.Config(**(cfg_overrides or {}))
    mod.ADAPT = mod.AdaptiveThresholds()               # start = sim time 0
    mod.SHARED = mod.SharedState()
    mod._prev_seizure_state = "NORMAL"
    mod._confirm_buf = deque(maxlen=mod.CFG.confirm_ticks)
    # `update_seizure_state` reads _confirm_buf as a module global → rebinding works

    times, states, feats, thr = [], [], [], []
    orig = getattr(mod.update_seizure_state, "__wrapped__", mod.update_seizure_state)
    orig_an = getattr(mod.analyse, "__wrapped__", mod.analyse)

    def traced(raw_class, alpha_r, beta_r, ll, dar, hfe):
        s = orig(raw_class, alpha_r, beta_r, ll, dar, hfe)
        times.append(clock.t - 1_000_000.0)
        states.append(STATE_CODE[s])
        if len(states) % 10 == 1:                      # thresholds at ~1 Hz
            A = mod.ADAPT
            thr.append((clock.t - 1_000_000.0, A.ll_brownout, A.dar_brownout, A.hfe_brownout,
                        A.ll_blackout, A.dar_blackout, A.hfe_blackout))
        return s

    def traced_an(samples):                            # every tick, incl. artifacts
        r = orig_an(samples)
        feats.append((clock.t - 1_000_000.0, r[4], r[5], r[6]))
        return r

    traced.__wrapped__ = orig; traced_an.__wrapped__ = orig_an
    mod.update_seizure_state = traced; mod.analyse = traced_an

    base, diff, st, thr_fw = fw_trace
    ser = _FakeSerial(mod, clock, adc, base, diff, st, thr_fw)
    try:
        mod.serial_reader(ser)
    finally:
        mod.update_seizure_state = orig; mod.analyse = orig_an
    return (np.asarray(times), np.asarray(states, dtype=np.int8), mod.SHARED.artifact_count,
            np.asarray(feats, dtype=np.float32).reshape(-1, 4),
            np.asarray(thr, dtype=np.float32).reshape(-1, 7))


# ═════════════════════════════════════════════════════════════════════════════
#  ESP32 firmware detector — faithful port of loop()
# ═════════════════════════════════════════════════════════════════════════════
FW = dict(
    EMA_ALPHA=0.01, ADAPT_WARMUP_MS=90000, ADAPT_INTERVAL_MS=30000,
    Z_B=2.5, Z_K=4.0, B_FLOOR=60, K_FLOOR=120, B_CEIL=1200, K_CEIL=2400,
    WF_FORGET=0.995, CONFIRM_B=20, CONFIRM_K=15, POSTICTAL_HOLD=400,
    SAMPLE_MS=5,
)


@njit(cache=True)
def _constrain(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


@njit(cache=True)
def _fw_loop(adc, ema_a, warm_ms, adapt_ms, zb, zk, bf, kf, bc, kc, lam,
             cb, ck, hold, sample_ms):
    n = adc.shape[0]
    # setup(): baseline = integer mean of first 200 samples (long sum / 200)
    ncal = 200 if n > 200 else n
    s = 0
    for i in range(ncal):
        s += adc[i]
    baseline = np.float32(s // ncal)
    # Welford seed
    wn = 0.0; wm = 0.0; wM2 = 0.0
    for _ in range(20):
        wn = lam * wn + 1.0
        d = 10.0 - wm
        wm += d / wn
        wM2 = lam * wM2 + d * (10.0 - wm)
    thrB = 80; thrK = 160
    state = 0; cB = 0; cK = 0; pcount = 0
    start_ms = ncal * sample_ms
    last_adapt = start_ms
    out_base = np.empty(n - ncal, np.float32)
    out_diff = np.empty(n - ncal, np.int32)
    out_state = np.empty(n - ncal, np.int8)
    out_thr = np.empty(n - ncal, np.int32)
    one_m = np.float32(1.0) - np.float32(ema_a)
    a32 = np.float32(ema_a)
    for j in range(n - ncal):
        i = j + ncal
        now = i * sample_ms
        x = adc[i]
        baseline = one_m * baseline + a32 * np.float32(x)
        diff = abs(x - int(baseline))
        if state == 0:
            xf = np.float64(np.float32(diff))
            wn = lam * wn + 1.0
            d = xf - wm
            wm += d / wn
            wM2 = lam * wM2 + d * (xf - wm)
        if (now - start_ms) >= warm_ms and (now - last_adapt) >= adapt_ms:
            mu = np.float32(wm)
            sig = np.float32(0.0) if wn < 2.0 else np.float32(np.sqrt(wM2 / wn))
            if sig >= 1.0:
                nb = _constrain(int(mu + np.float32(zb) * sig), bf, bc)
                nk = _constrain(int(mu + np.float32(zk) * sig), kf, kc)
                if nk <= nb:
                    nk = nb + 40
                thrB = nb; thrK = nk
            last_adapt = now
        if state == 0:
            if diff >= thrK:
                cK += 1
                if cK >= ck:
                    state = 2; cK = 0; cB = 0
            elif diff >= thrB:
                cK = 0
                cB += 1
                if cB >= cb:
                    state = 1; cB = 0
            else:
                if cB > 0: cB -= 1
                if cK > 0: cK -= 1
        elif state == 1:
            if diff >= thrK:
                cK += 1
                if cK >= ck:
                    state = 2; cK = 0
            elif diff < thrB:
                cB += 1
                if cB >= cb:
                    state = 0; cB = 0
            else:
                cB = 0; cK = 0
        elif state == 2:
            if diff < thrB:
                state = 3; pcount = hold
        else:
            pcount -= 1
            if pcount <= 0 and diff < thrB:
                state = 0
        out_base[j] = baseline; out_diff[j] = diff
        out_state[j] = state; out_thr[j] = thrB
    return ncal, out_base, out_diff, out_state, out_thr


def run_firmware_detector(adc, **over):
    p = dict(FW, **over)
    ncal, base, diff, st, thr = _fw_loop(
        np.ascontiguousarray(adc, dtype=np.int32), p["EMA_ALPHA"],
        p["ADAPT_WARMUP_MS"], p["ADAPT_INTERVAL_MS"], p["Z_B"], p["Z_K"],
        p["B_FLOOR"], p["K_FLOOR"], p["B_CEIL"], p["K_CEIL"], p["WF_FORGET"],
        p["CONFIRM_B"], p["CONFIRM_K"], p["POSTICTAL_HOLD"], p["SAMPLE_MS"])
    t = (np.arange(len(st)) + ncal) * DT
    return ncal, t, st, (base, diff, st, thr)
