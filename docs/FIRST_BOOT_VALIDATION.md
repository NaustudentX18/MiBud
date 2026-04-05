# First Boot Validation Guide

Use this guide to verify MiBud is working correctly after initial setup on your Pi Zero 2 W.

---

## Quick Validation

Run the built-in boot check:

```bash
bash scripts/first_boot_check.sh
```

This script verifies the most critical services and hardware before you go live.

---

## Manual Checklist

### 1 — Python Environment
```bash
source venv/bin/activate
python --version   # should be 3.10+
python -c "import core.config; print('✅ core imports OK')"
```

### 2 — Configuration
```bash
cat config/config.json | python -m json.tool   # valid JSON?
```

Expected keys: `ai`, `personality`, `features`, `api_keys`.

### 3 — Hardware Detection

```bash
# I²C bus (WM8960 audio + PiSugar battery)
i2cdetect -y 1

# SPI (ST7789 display)
ls /dev/spidev*

# Audio devices
aplay -l
arecord -l
```

### 4 — Web Interface
```bash
source venv/bin/activate
python -m web.server &
sleep 3
curl -s http://localhost:5000/api/status | python -m json.tool
```

Expected: JSON response with `state`, `battery`, `personality` fields.

### 5 — AI Chat (requires API key or Ollama)
```bash
source venv/bin/activate
python demo.py
```

### 6 — Service Auto-Start (after running `bash scripts/install.sh`)
```bash
sudo systemctl status mibud
# Expected: active (running)
```

---

## Battery Validation

| Test | Pass Criteria |
|------|--------------|
| Cold boot (bench power) | App running within 30 s |
| Cold boot (battery, full charge) | App running within 30 s |
| Cold boot (battery, ~30 %) | App running within 30 s |
| Sudden power loss then reboot | No config corruption |
| Low battery warning | LED / log shows alert below 20 % |

---

## What to Check in Logs

```bash
journalctl -u mibud -n 100 --no-pager
# or
tail -100 logs/mibud.log
```

Look for:
- `✅ Config loaded`
- `✅ Hardware initialized` (or mock hardware on non-Pi)
- `🚀 MiBud ready`
- No `CRITICAL` or unhandled exception lines

---

## Common First-Boot Failures

| Symptom | Resolution |
|---------|-----------|
| `ModuleNotFoundError` | Re-run `bash scripts/setup.sh` |
| Flask 500 on `/api/status` | Check `config/config.json` exists |
| Display blank after boot | Verify SPI enabled and HAT driver installed |
| No sound | Verify I²C enabled; check `aplay -l` |
| Battery reads 0 % | PiSugar I²C address conflict; reboot |
