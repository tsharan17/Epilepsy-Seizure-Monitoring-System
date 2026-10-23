/*
  mpu9250_bringup.ino — 5-minute hardware check for the EEG-plus-motion build.
  Wiring (ESP32 DevKit):  MPU9250 VCC->3V3  GND->GND  SDA->GPIO21  SCL->GPIO22  AD0->GND
  Open Serial Monitor at 115200 baud. Expected:
    [SCAN] device at 0x68                 (0x69 if AD0 is tied to 3V3)
    [IMU] WHO_AM_I=0x71 -> OK             (0x73 = MPU9255, 0x70 = MPU6500: also fine)
    lying flat & still: |a| ≈ 1.00 g, gyro within ±3 dps
    shake the board: acc and gyro values jump
    [EEG] loop rate ≈ 190-200 samples/s   (measured with the delay(5) pacing)
*/
#include <Wire.h>
#include "mpu9250.h"

MPU9250 imu;
unsigned long t0, tPrint, nEEG = 0;

void setup() {
  Serial.begin(115200); delay(500);
  Wire.begin(21, 22, 400000);
  for (uint8_t a = 1; a < 127; ++a) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) Serial.printf("[SCAN] device at 0x%02X\n", a);
  }
  bool ok = imu.begin(21, 22, MPU9250::ADDR_LO);
  if (!ok) ok = imu.begin(21, 22, MPU9250::ADDR_HI);
  Serial.printf("[IMU] WHO_AM_I=0x%02X -> %s\n", imu.whoami, ok ? "OK" : "FAIL (check wiring/address)");
  t0 = tPrint = millis();
}

void loop() {
  analogRead(34); ++nEEG; delay(5);                 // same pacing as the monitor firmware
  if (millis() - tPrint >= 1000) {
    tPrint += 1000;
    if (imu.read()) {
      float g = sqrtf(imu.ax * imu.ax + imu.ay * imu.ay + imu.az * imu.az);
      Serial.printf("acc[g] %.3f %.3f %.3f |a|=%.3f  gyro[dps] %.1f %.1f %.1f\n",
                    imu.ax, imu.ay, imu.az, g, imu.gx, imu.gy, imu.gz);
    }
    Serial.printf("[EEG] loop rate = %lu samples/s\n", nEEG); nEEG = 0;
  }
}
