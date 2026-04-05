# MiBud Hardware Guide

## 🧩 Supported Hardware

### Core
| Component | Model | Notes |
|-----------|-------|-------|
| SBC | Raspberry Pi Zero 2 W | ARM Cortex-A53 quad-core 1 GHz, 512 MB RAM |
| AI HAT | Whisplay AI HAT | 240×280 ST7789 display, WM8960 audio codec |
| Battery | PiSugar 3 | 1200 mAh, I²C battery management, 8+ hr runtime |

---

## 🗺️ Pin Map (Whisplay HAT)

### Display (ST7789 — SPI0)
| Signal | GPIO |
|--------|------|
| SPI MOSI | GPIO 10 |
| SPI CLK | GPIO 11 |
| SPI CS | GPIO 8 |
| DC | GPIO 25 |
| RST | GPIO 27 |
| BL | GPIO 24 |

### Audio (WM8960 — I²C + I²S)
| Signal | GPIO |
|--------|------|
| SDA | GPIO 2 |
| SCL | GPIO 3 |
| I²S BCLK | GPIO 18 |
| I²S LRCLK | GPIO 19 |
| I²S DOUT | GPIO 21 |

### Buttons
| Button | GPIO | Default action |
|--------|------|----------------|
| Button A | GPIO 5 | Short: listen · Long: cancel · Hold: stop |
| Button B | GPIO 6 | Short: cycle personality · Long: settings |

### LED (RGB)
| Channel | GPIO |
|---------|------|
| Red | GPIO 16 |
| Green | GPIO 20 |
| Blue | GPIO 26 |

### PiSugar 3 (I²C)
| Signal | GPIO |
|--------|------|
| SDA | GPIO 2 (shared) |
| SCL | GPIO 3 (shared) |
| I²C Address | 0x57 |

---

## 🔧 Setup

### Enable Interfaces
```bash
# SPI (for display)
sudo raspi-config nonint do_spi 0
# I²C (for audio codec + battery)
sudo raspi-config nonint do_i2c 0
```

### Install Whisplay HAT Driver
```bash
git clone https://github.com/PiSugar/Whisplay.git --depth 1 /home/pi/Whisplay
cd /home/pi/Whisplay/Driver
sudo bash install_wm8960_driver.sh
```

### Verify Hardware
```bash
# Check I²C devices (WM8960 @ 0x1a, PiSugar @ 0x57)
i2cdetect -y 1

# Check SPI
ls /dev/spidev*

# Check audio
aplay -l
```

---

## 🔋 Battery Notes

- PiSugar 3 supports safe shutdown trigger via GPIO 26 (configurable)
- Monitor battery via I²C: address `0x57`, register `0xa2` for percentage
- MiBud reads battery state every 60 s and logs warnings below 20 %

---

## 📷 Camera (Optional)

- **Picamera2** (CSI ribbon): preferred; auto-detected on Pi
- **USB Camera**: OpenCV fallback; plug in before boot
- Camera is optional — all non-vision features work without it

---

## 🛠️ Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| No audio / WM8960 not found | I²C not enabled | `sudo raspi-config nonint do_i2c 0` |
| Display blank | SPI not enabled | `sudo raspi-config nonint do_spi 0` |
| Battery level stuck at 100 % | PiSugar driver not loaded | Reboot after driver install |
| High CPU / slow TTS | Pi thermal throttle | Add heatsink or reduce model size |
