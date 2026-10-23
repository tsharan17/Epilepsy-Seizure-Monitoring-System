"""System / wiring figure for the device (EEG front-end + MPU9250 + ESP32)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

fig, ax = plt.subplots(figsize=(7.2, 2.75), dpi=300)
ax.set_xlim(0, 100); ax.set_ylim(0, 40); ax.axis("off")
C = dict(eeg="#dbe9f6", imu="#fde7cf", mcu="#e3f1df", out="#eeeeee")


def box(x, y, w, h, title, sub, col):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2", fc=col, ec="#333", lw=0.8))
    ax.text(x + w / 2, y + h - 2.2, title, ha="center", va="top", fontsize=7.2, weight="bold")
    ax.text(x + w / 2, y + h - 5.6, sub, ha="center", va="top", fontsize=5.6, linespacing=1.25)


def arrow(x1, y1, x2, y2, lab="", dy=1.0):
    ax.annotate("", (x2, y2), (x1, y1), arrowprops=dict(arrowstyle="-|>", lw=0.8, color="#333", shrinkA=0, shrinkB=0))
    if lab:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + dy, lab, ha="center", va="bottom", fontsize=5.3, color="#333")


box(0.5, 24, 15, 13, "Electrodes", "Ag/AgCl\nFP1(+) FP2(−)\nearlobe ground", C["eeg"])
box(20, 24, 15, 13, "BioAmp Pill", "gain ≈1000\n0.5–40 Hz\n3.3 V supply", C["eeg"])
box(39.5, 24, 13, 13, "Buffer + RC", "LM358 follower\n10 kΩ / 100 nF", C["eeg"])
box(0.5, 3, 34.5, 14, "MPU9250 IMU (on headband)", "3-axis accel ±4 g, 3-axis gyro ±500 °/s\n25 Hz output, 10 Hz DLPF (magnetometer unused)\nVCC 3V3 · GND · SDA · SCL · AD0→GND (0x68)", C["imu"])
box(58, 3, 22, 34, "ESP32", "GPIO34  ADC1 (EEG, 12-bit)\nGPIO21  I2C SDA\nGPIO22  I2C SCL\nGPIO35  battery ADC\n\nfirmware:\ninitial state machine\n+ DEV-BR (EEG)\n+ MOV-BR (motion)\n→ fused alarm, 90 s\n<7 KB detector RAM", C["mcu"])
box(85, 22, 14.5, 15, "Local alarm", "RGB LED\n(GPIO25/26/27)\n500-ms pulse\n(GPIO18)", C["out"])
box(85, 3, 14.5, 15, "Wi-Fi AP", "REST /status\n/eeg /simulate\nphone app\n(offline)", C["out"])
arrow(15.9, 30.5, 19.6, 30.5)
arrow(35.4, 30.5, 39.1, 30.5)
arrow(52.9, 30.5, 57.6, 30.5, "analog")
arrow(35.4, 10, 57.6, 10, "I²C 400 kHz")
arrow(80.4, 29.5, 84.6, 29.5)
arrow(80.4, 10.5, 84.6, 10.5)
plt.savefig("figures/system.png", bbox_inches="tight", pad_inches=0.02)
