# Wiring reference

Exact analog wiring is drawn in [`../docs/circuit_diagram.png`](../docs/circuit_diagram.png); the block view is in [`../docs/block_diagram.png`](../docs/block_diagram.png) and the system view in [`../docs/system_diagram.png`](../docs/system_diagram.png).

## Signal chain

`Ag/AgCl electrodes (FP1 +, FP2 −, ear-lobe ground) → EXG BioAmp Pill (gain ≈ 1000, 0.5–40 Hz) → LM358 voltage follower → 10 kΩ / 100 nF RC filter → ESP32 GPIO34`

* RC corner frequency: f_c = 1 / (2π · 10 kΩ · 100 nF) ≈ 159 Hz.
* The ADC is 12-bit with the default attenuation; the firmware loop uses `delay(5)` (≈ 200 samples/s).
* The LM358 is not rail-to-rail: on a 3.3 V supply its output tops out near 1.8 V, about 150 mV above mid-supply, which can clip large artifacts.
* The BioAmp Pill is documented for 5 V supply; the prototype runs it at 3.3 V.
* Gain and pass-band are nominal values from the documentation and have not been measured on this build.

## ESP32 pins

| GPIO | Function |
|---|---|
| 34 | EEG signal in (ADC1_CH6, input only) |
| 35 | Battery voltage divider (ADC1_CH7, input only) |
| 2 | Onboard heartbeat LED |
| 18 | Mobile/BT trigger — 500 ms HIGH on BLACKOUT |
| 25 / 26 / 27 | RGB LED: Green / Red / Blue |
| 21 / 22 | I²C SDA / SCL (MPU9250) |

## MPU9250 head-motion sensor (EEG-plus-motion firmware)

| MPU9250 pin | ESP32 pin | Note |
|---|---|---|
| VCC | 3V3 | GY-9250 breakouts have their own regulator; 3.3 V is fine |
| GND | GND | common ground with the BioAmp and battery |
| SDA | GPIO21 | I²C data, 400 kHz |
| SCL | GPIO22 | I²C clock |
| AD0 | GND | address 0x68 (3V3 for 0x69) |
| INT, NCS, FSYNC, EDA, ECL | not connected | the sensor is polled at 25 Hz |

Mount the sensor on the headband so that it moves with the head, and keep the I²C wires away from the electrode leads and the BioAmp input. The MPU-9250 is end of life; the MPU-6500 and MPU-9255 use the same registers and the driver accepts their WHO_AM_I values (0x70, 0x73). Use `firmware/mpu9250_bringup` to check the wiring before flashing the main firmware.

## Power and safety

There is no galvanic isolation. When electrodes touch skin, power the board only from a USB battery bank, never from a mains-connected supply.
