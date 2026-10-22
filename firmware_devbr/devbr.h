// devbr.h — DEV-BR baseline-ratio seizure detector (portable C++, Arduino/ESP32-ready)
//
// Feeds on the per-sample deviation d[n] = |x[n] - (int)baseline| that the
// existing firmware already computes.  Once per second:
//   delta(t) = mean of d over second t
//   beta(t)  = median of delta over seconds [t-329, t-30]   (300 values, 30-s lag)
//   above(t) = delta(t) >= r * beta(t)
//   alarm at t+1 when `above` has held for D consecutive seconds (rising edge),
//   suppressed if a previous alarm was raised < 90 s earlier.
// No alarm is possible before t = 330 s (baseline warm-up).
//
// Memory: one ring of 330 floats + one scratch array of 300 floats ≈ 2.5 KB.
// Work per second: one 300-element copy + std::nth_element (linear time).
//
// This header is verified bit-for-bit against the Python evaluation
// (evaluation/personalize.py) by devbr_test.cpp.  It has NOT yet been
// integrated into, or timed on, the ESP32 firmware.
#pragma once
#include <stdint.h>
#include <math.h>
#include <algorithm>

class DevBR {
 public:
  static const int WIN = 300;          // baseline window (s)
  static const int LAG = 30;           // baseline lag (s)
  static const int HIST = WIN + LAG;   // seconds of history kept
  static const int MERGE = 90;         // alarm refractory period (s)

  DevBR(float ratio = 1.5f, int persist_s = 15, int fs = 200)
      : r_(ratio), D_(persist_s), fs_(fs) { reset(); }

  void reset() {
    t_ = 0; head_ = 0; acc_ = 0.0; n_ = 0; run_ = 0; prevAbove_ = false;
    lastAlarm_ = -1e9; for (int i = 0; i < HIST; ++i) hist_[i] = NAN;
  }

  // Per-sample entry point (call from loop() with the firmware's `diff`).
  // Returns true on the sample that completes a second in which an alarm fires.
  bool pushSample(int d) {
    acc_ += d; if (++n_ < fs_) return false;
    float delta = (float)(acc_ / n_); acc_ = 0.0; n_ = 0;
    return pushSecond(delta);
  }

  // Per-second entry point (also used by the verification harness).
  bool pushSecond(float delta) {
    hist_[head_] = delta; head_ = (head_ + 1) % HIST;   // hist_ now ends at second t_
    bool alarm = false;
    bool above = false;
    if (t_ >= HIST) {
      float beta = baseline();
      if (isfinite(beta) && isfinite(delta)) {
        double lr = log(fmax((double)delta, 1e-9)) - log(fmax((double)beta, 1e-9));
        above = lr >= log((double)r_);
      }
    }
    run_ = above ? run_ + 1 : 0;
    bool trig = run_ >= D_;
    if (trig && !prevTrig_) {
      double at = (double)t_ + 1.0;
      if (at - lastAlarm_ >= MERGE) { lastAlarm_ = at; alarm = true; }
    }
    prevTrig_ = trig;
    ++t_;
    return alarm;
  }

  double lastAlarmTime() const { return lastAlarm_; }

 private:
  // median of the 300 values for seconds [t-329, t-30]
  float baseline() {
    // newest value (second t) is at head_-1; second t-k is at head_-1-k
    for (int k = LAG; k < LAG + WIN; ++k) {
      int idx = (head_ - 1 - k + 2 * HIST) % HIST;
      tmp_[k - LAG] = hist_[idx];
    }
    float* mid = tmp_ + WIN / 2;
    std::nth_element(tmp_, mid, tmp_ + WIN);
    float hi = *mid;
    float lo = *std::max_element(tmp_, mid);
    return 0.5f * (lo + hi);              // even-length median (as pandas)
  }

  float r_; int D_; int fs_;
  long t_; int head_; double acc_; int n_; int run_;
  bool prevAbove_; bool prevTrig_ = false; double lastAlarm_;
  float hist_[HIST]; float tmp_[WIN];
};
