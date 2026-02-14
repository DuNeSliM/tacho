# Pi Digital Car Dashboard (OBD2 over WiFi)

This project reads OBD2 values from a WiFi ELM327 adapter and shows them on a custom dashboard.

- The Raspberry Pi screen shows a fullscreen dashboard automatically at boot.
- The same data is available on your smartphone from the Pi web server.
- Works on Raspberry Pi OS Lite (32-bit) with Python.

## How it works

1. Pi connects to OBD adapter WiFi (`wlan0`).
2. Python backend polls OBD2 PIDs over TCP (`app/telemetry.py`).
3. Backend serves live state via HTTP API (`/api/state`).
4. Dashboard web UI (local kiosk + phone browser) polls API and renders stats.

## Recommended network topology

Use two WiFi interfaces:

- `wlan0`: OBD adapter connection.
- `wlan1` (USB dongle): hotspot for your phone.

See `docs/network_setup.md` for full setup.

## Project structure

```text
app/
  config.py
  telemetry.py
  server.py
static/
  index.html
  styles.css
  app.js
scripts/
  start-kiosk.sh
systemd/
  pidash.service
  pidash-kiosk.service
docs/
  network_setup.md
run.py
```

## Install on Raspberry Pi

### One-command installer

```bash
cd /home/pi/tacho
bash install.sh
```

This installs packages, creates `.venv`, installs Python deps, installs/enables `systemd` services, and starts the dashboard.

You still need to verify `.env` (especially `OBD_HOST` and `OBD_PORT`).

1. Install packages:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git python3-venv python3-pip curl xserver-xorg xinit openbox chromium || sudo apt install -y git python3-venv python3-pip curl xserver-xorg xinit openbox chromium-browser
```

2. Create virtual env and install Python deps:

```bash
cd /home/pi/tacho
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

3. Edit `.env` values:

```env
OBD_HOST=192.168.0.10
OBD_PORT=35000
POLL_INTERVAL=0.40
RECONNECT_DELAY=3.0
HTTP_HOST=0.0.0.0
HTTP_PORT=8080
SIMULATE=false
```

4. Make kiosk script executable:

```bash
chmod +x /home/pi/tacho/scripts/start-kiosk.sh
```

5. Install systemd services:

```bash
sudo cp /home/pi/tacho/systemd/pidash.service /etc/systemd/system/pidash.service
sudo cp /home/pi/tacho/systemd/pidash-kiosk.service /etc/systemd/system/pidash-kiosk.service
sudo systemctl daemon-reload
sudo systemctl enable pidash pidash-kiosk
sudo systemctl start pidash pidash-kiosk
```

6. Check service status:

```bash
systemctl status pidash --no-pager
systemctl status pidash-kiosk --no-pager
```

## Boot behavior in car

When the car powers the Pi:

1. Pi boots.
2. `pidash` backend service starts.
3. `pidash-kiosk` starts Chromium fullscreen on HDMI.
4. Dashboard appears automatically.

## Smartphone access

- Same network: `http://<PI-IP>:8080`
- Pi hotspot setup: `http://192.168.50.1:8080`

## Testing without real car data

Set in `.env`:

```env
SIMULATE=true
```

Restart services:

```bash
sudo systemctl restart pidash pidash-kiosk
```

## Logs

```bash
journalctl -u pidash -f
journalctl -u pidash-kiosk -f
```

## Safety note

Use this as an auxiliary display only. Mount hardware securely and avoid interacting with the dashboard while driving.
