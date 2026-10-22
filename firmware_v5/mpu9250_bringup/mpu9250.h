// mpu9250.h — minimal register-level MPU-9250 driver for the ESP32 (Arduino Wire).
// Accelerometer + gyroscope only (the AK8963 magnetometer is not used).
// Configured to match the evaluation data: 25 Hz output rate, ~10 Hz DLPF,
// ±4 g, ±500 °/s.  No external library needed.
#pragma once
#include <Arduino.h>
#include <Wire.h>

class MPU9250 {
 public:
  static const uint8_t ADDR_LO = 0x68;   // AD0 -> GND
  static const uint8_t ADDR_HI = 0x69;   // AD0 -> 3V3
  float ax, ay, az;      // g
  float gx, gy, gz;      // deg/s
  uint8_t whoami = 0;

  // Returns true if a MPU-9250/9255/6500 answered.
  bool begin(int sda = 21, int scl = 22, uint8_t addr = ADDR_LO, uint32_t hz = 400000) {
    addr_ = addr;
    Wire.begin(sda, scl, hz);
    write(0x6B, 0x80); delay(100);         // PWR_MGMT_1: device reset
    write(0x6B, 0x01); delay(10);          // clock = PLL (gyro X)
    write(0x6C, 0x00);                     // PWR_MGMT_2: all axes on
    whoami = read8(0x75);                  // 0x71 MPU9250, 0x73 MPU9255, 0x70 MPU6500
    if (whoami != 0x71 && whoami != 0x73 && whoami != 0x70) return false;
    write(0x1A, 0x05);                     // CONFIG: gyro DLPF 10 Hz -> internal rate 1 kHz
    write(0x19, 39);                       // SMPLRT_DIV: 1 kHz / (1+39) = 25 Hz
    write(0x1B, 0x08);                     // GYRO_CONFIG: ±500 dps
    write(0x1C, 0x08);                     // ACCEL_CONFIG: ±4 g
    write(0x1D, 0x05);                     // ACCEL_CONFIG2: DLPF 10.2 Hz
    ok_ = true;
    return true;
  }

  bool ok() const { return ok_; }

  // Burst-read accel, temperature and gyro (14 bytes from ACCEL_XOUT_H).
  bool read() {
    if (!ok_) return false;
    Wire.beginTransmission(addr_); Wire.write(0x3B);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom((int)addr_, 14) != 14) return false;
    int16_t v[7];
    for (int i = 0; i < 7; ++i) v[i] = (int16_t)((Wire.read() << 8) | Wire.read());
    ax = v[0] / 8192.0f; ay = v[1] / 8192.0f; az = v[2] / 8192.0f;   // LSB/g at ±4 g
    gx = v[4] / 65.5f;   gy = v[5] / 65.5f;   gz = v[6] / 65.5f;     // LSB/(°/s) at ±500 dps
    return true;
  }

 private:
  uint8_t addr_ = ADDR_LO; bool ok_ = false;
  void write(uint8_t reg, uint8_t val) {
    Wire.beginTransmission(addr_); Wire.write(reg); Wire.write(val); Wire.endTransmission();
  }
  uint8_t read8(uint8_t reg) {
    Wire.beginTransmission(addr_); Wire.write(reg); Wire.endTransmission(false);
    Wire.requestFrom((int)addr_, 1); return Wire.available() ? Wire.read() : 0xFF;
  }
};
