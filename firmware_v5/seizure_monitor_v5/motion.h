// motion.h — per-second head-motion features from a 25-Hz IMU stream.
// Identical definitions to the evaluation (s2_extract.py: motion_feats):
//   acc_act(t) = mean over second t of || a - EMA_1s(a) ||      (high-passed acceleration)
//   gyr_act(t) = mean over second t of || omega ||
//   rhythm(t)  = share of 2-7 Hz power (Hann window, last 4 s) in 0.5-12 Hz of ||a - EMA(a)||
// All three are scale-free once divided by the wearer's own delayed median
// (see MovBR in vera_detect.h), so the sensor's units do not matter.
// Memory: ~1.6 KB.  Work: 3 axis updates per sample + one table-driven 47-bin DFT per second.
#pragma once
#include <math.h>

class MotionFeatures {
 public:
  static const int FS = 25;          // IMU output rate (Hz)
  static const int W = 100;          // 4-s rhythm window
  float acc_act = NAN, gyr_act = NAN, rhythm = NAN;

  MotionFeatures() { reset(); }
  void reset() {
    init_ = false; n_ = 0; accSum_ = gyrSum_ = 0.0; head_ = 0; filled_ = 0; secs_ = 0;
    for (int i = 0; i < W; ++i) ring_[i] = 0.0f;
    // Hann window and DFT bin selection precomputed once
    for (int i = 0; i < W; ++i) {
      hann_[i] = 0.5f - 0.5f * cosf(2.0f * (float)M_PI * i / (W - 1));
      cos_[i] = cosf(2.0f * (float)M_PI * i / W); sin_[i] = sinf(2.0f * (float)M_PI * i / W);
    }
  }

  // Push one IMU sample (any units, e.g. g and deg/s). Returns true when a
  // second has completed and the three features have been updated.
  bool push(float ax, float ay, float az, float gx, float gy, float gz) {
    const float a = 1.0f / FS;
    if (!init_) { lx_ = ax; ly_ = ay; lz_ = az; init_ = true; }
    lx_ += a * (ax - lx_); ly_ += a * (ay - ly_); lz_ += a * (az - lz_);
    float hx = ax - lx_, hy = ay - ly_, hz = az - lz_;
    float mag = sqrtf(hx * hx + hy * hy + hz * hz);
    accSum_ += mag;
    gyrSum_ += sqrtf(gx * gx + gy * gy + gz * gz);
    ring_[head_] = mag; head_ = (head_ + 1) % W; if (filled_ < W) ++filled_;
    if (++n_ < FS) return false;
    acc_act = (float)(accSum_ / n_); gyr_act = (float)(gyrSum_ / n_);
    accSum_ = gyrSum_ = 0.0; n_ = 0; ++secs_;
    rhythm = (secs_ >= 4 && filled_ == W) ? rhythmShare() : NAN;
    return true;
  }

 private:
  float rhythmShare() {
    float mean = 0; for (int i = 0; i < W; ++i) mean += ring_[i]; mean /= W;
    double num = 0, den = 1e-12;
    float v[W];
    for (int i = 0; i < W; ++i) v[i] = (ring_[(head_ + i) % W] - mean) * hann_[i];
    // bin k has frequency k * FS / W = 0.25 k Hz; 0.5-12 Hz -> k = 2..48; 2-7 Hz -> k = 8..28
    // twiddle factors from a 100-entry table: angle index (k*i) mod W
    for (int k = 2; k <= 48; ++k) {
      float re = 0, im = 0; int idx = 0;
      for (int i = 0; i < W; ++i) {
        re += v[i] * cos_[idx]; im -= v[i] * sin_[idx];
        idx += k; if (idx >= W) idx -= W;
      }
      double p = re * re + im * im;
      den += p; if (k >= 8 && k <= 28) num += p;
    }
    return (float)(num / den);
  }
  bool init_; int n_; double accSum_, gyrSum_; float lx_, ly_, lz_;
  float ring_[W]; float hann_[W]; float cos_[W]; float sin_[W]; int head_, filled_; long secs_;
};
