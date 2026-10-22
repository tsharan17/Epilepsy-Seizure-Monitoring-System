// vera_detect.h — multimodal seizure alarm used by firmware v5.
//
//   EEG condition  E(t): log(dev(t) / median dev[t-329..t-30])  >= log(rE)   held for DE s
//   MOV condition  M(t): log(acc(t) / median acc[t-329..t-30])  >= log(rM)
//                        AND rhythm(t) >= qM                               held for DM s
//   EVENT  (general mode): rising edge of (E or M)                -> BROWNOUT warning
//   ALARM  (convulsive mode): Ec(t) and Mc(t) both true for DC s, with
//          Ec: EEG log-ratio >= log(rEc), Mc: motion log-ratio >= log(rMc)  -> BLACKOUT alarm
//   each output fires at t+1 at most once per 90 s.
// dev = per-second mean of the firmware's EEG deviation |x - (int)baseline|,
// acc / rhythm = MotionFeatures (motion.h).  No alarm before t = 330 s.
// Bit-for-bit equivalent to evaluation/s2_eval.py (checked by vera_detect_test.cpp).
// Memory: two 330-value rings + two 300-value scratch arrays ≈ 5.0 KB.
#pragma once
#include <math.h>
#include <algorithm>

class DelayedMedianRatio {
 public:
  static const int WIN = 300, LAG = 30, HIST = WIN + LAG;
  DelayedMedianRatio() { reset(); }
  void reset() { t_ = 0; head_ = 0; for (int i = 0; i < HIST; ++i) hist_[i] = NAN; }
  // push this second's value; returns log(x / delayed median), or -INF while warming up
  double push(float x) {
    hist_[head_] = x; head_ = (head_ + 1) % HIST;
    double out = -INFINITY;
    if (t_ >= HIST) {
      double b = median();
      if (isfinite(b) && isfinite(x)) out = log(fmax((double)x, 1e-9) / fmax(b, 1e-9));   // same order of operations as the evaluation
    }
    ++t_;
    return out;
  }
  long t() const { return t_; }
 private:
  double median() {
    int m = 0;
    for (int k = LAG; k < LAG + WIN; ++k) {
      float v = hist_[(head_ - 1 - k + 2 * HIST) % HIST];
      if (isfinite(v)) tmp_[m++] = v;           // pandas ignores NaN (min_periods = 150)
    }
    if (m < WIN / 2) return NAN;
    float* mid = tmp_ + m / 2;
    std::nth_element(tmp_, mid, tmp_ + m);
    if (m % 2) return (double)*mid;
    float lo = *std::max_element(tmp_, mid);
    return 0.5 * ((double)lo + (double)*mid);               // double, as pandas
  }
  long t_; int head_; float hist_[HIST]; float tmp_[WIN];
};

struct VeraParams {
  float rE = 2.0f; int DE = 20;            // EEG ratio / persistence (s)
  float rM = 24.0f; int DM = 20; float qM = 0.4f;  // motion ratio / persistence / rhythm gate
  bool useEEG = true, useMOV = true;
  float rEc = 4.0f, rMc = 8.0f; int DC = 30;       // convulsive (co-activation) alarm
};

// rising-edge trigger with a 90-s refractory period (same as the evaluation's onsets())
struct EdgeAlarm {
  bool prev = false; double last = -1e9;
  bool step(bool trig, double at) {
    bool fire = false;
    if (trig && !prev && at - last >= 90.0) { last = at; fire = true; }
    prev = trig; return fire;
  }
};

class VeraDetector {
 public:
  enum Source { NONE = 0, EEG = 1, MOV = 2, BOTH = 3 };
  explicit VeraDetector(const VeraParams& p = VeraParams()) : p_(p) { reset(); }
  void reset() { e_.reset(); m_.reset(); runE_ = runM_ = runC_ = 0; prevTrig_ = false; lastAlarm_ = -1e9; t_ = 0;
                 lrE = lrM = -INFINITY; conv_ = EdgeAlarm(); convulsive = false; }
  // one call per second; movOk = false if the IMU is absent (motion branch disabled)
  // returns Source of a new alarm (NONE if no alarm this second)
  Source pushSecond(float dev, float acc, float rhythm, bool movOk) {
    lrE = e_.push(dev);
    lrM = movOk ? m_.push(acc) : -INFINITY;
    bool aE = p_.useEEG && lrE >= log((double)p_.rE);
    bool aM = p_.useMOV && movOk && lrM >= log((double)p_.rM) && (p_.qM <= 0.0f || rhythm >= p_.qM);
    runE_ = aE ? runE_ + 1 : 0;  runM_ = aM ? runM_ + 1 : 0;
    bool tE = runE_ >= p_.DE, tM = runM_ >= p_.DM;
    bool aC = movOk && lrE >= log((double)p_.rEc) && lrM >= log((double)p_.rMc);
    runC_ = aC ? runC_ + 1 : 0;
    convulsive = conv_.step(runC_ >= p_.DC, (double)t_ + 1.0);
    bool trig = tE || tM;
    Source s = NONE;
    if (trig && !prevTrig_) {
      double at = (double)t_ + 1.0;
      if (at - lastAlarm_ >= 90.0) { lastAlarm_ = at; s = (Source)((tE ? EEG : 0) | (tM ? MOV : 0)); }
    }
    prevTrig_ = trig; ++t_;
    return s;
  }
  double lrE, lrM;                    // latest log-ratios (for telemetry)
  bool convulsive;                    // true in the second a convulsive (co-activation) alarm fires
  double lastConvulsiveTime() const { return conv_.last; }
  double lastAlarmTime() const { return lastAlarm_; }
 private:
  VeraParams p_; DelayedMedianRatio e_, m_;
  int runE_, runM_, runC_; bool prevTrig_; EdgeAlarm conv_; double lastAlarm_; long t_;
};
