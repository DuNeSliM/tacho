# Pi Digitales Armaturenbrett (OBD2 WiFi)

Dieses Projekt liest OBD2-Werte und zeigt sie als digitales Dashboard auf dem Pi-Bildschirm. Gleichzeitig stellt der Pi die Daten als Webseite fuer dein Handy bereit.

## Zielbild beim Einschalten
- Auto bekommt Strom -> Raspberry Pi bootet.
- `pidash` Backend startet automatisch.
- Chromium Kiosk startet automatisch auf HDMI und zeigt `http://127.0.0.1:8080`.
- Handy kann parallel dieselben Daten vom Pi holen.

## Voraussetzungen
- Raspberry Pi OS Lite (32-bit) empfohlen.
- Python 3.10+.
- OBD2 WiFi Adapter (ELM327 kompatibel).
- Fuer OBD + Handy parallel: zweiter USB-WiFi Adapter empfohlen (siehe `docs/network_setup.md`).

## Projektstruktur

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

## Schritt-fuer-Schritt auf einem neuen Pi

1. Systempakete installieren:
```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git python3-venv python3-pip curl xserver-xorg xinit openbox chromium || sudo apt install -y git python3-venv python3-pip curl xserver-xorg xinit openbox chromium-browser
```

2. Projekt auf den Pi kopieren (am besten per `git clone` oder `scp`) und dann:
```bash
cd /home/pi/tacho
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

3. `.env` bearbeiten:
```env
OBD_HOST=192.168.0.10
OBD_PORT=35000
POLL_INTERVAL=0.40
RECONNECT_DELAY=3.0
HTTP_HOST=0.0.0.0
HTTP_PORT=8080
SIMULATE=false
```

4. Kiosk-Skript ausfuehrbar machen:
```bash
chmod +x /home/pi/tacho/scripts/start-kiosk.sh
```

5. Services installieren:
```bash
sudo cp /home/pi/tacho/systemd/pidash.service /etc/systemd/system/pidash.service
sudo cp /home/pi/tacho/systemd/pidash-kiosk.service /etc/systemd/system/pidash-kiosk.service
sudo systemctl daemon-reload
sudo systemctl enable pidash pidash-kiosk
sudo systemctl start pidash pidash-kiosk
```

6. Status pruefen:
```bash
systemctl status pidash --no-pager
systemctl status pidash-kiosk --no-pager
```

7. Neustarttest:
```bash
sudo reboot
```
Nach dem Reboot sollte der Bildschirm automatisch das Dashboard zeigen.

## Test ohne Auto

Setze in `.env`:
```env
SIMULATE=true
```
Dann:
```bash
sudo systemctl restart pidash pidash-kiosk
```

## Handy-Zugriff
- Im gleichen Netz: `http://<PI-IP>:8080`
- Oder ueber Pi-Hotspot mit zweitem WLAN-Adapter: `http://192.168.50.1:8080`

## Logs bei Fehlern
```bash
journalctl -u pidash -f
journalctl -u pidash-kiosk -f
```

## Sicherheitshinweise
- Nur als Zusatzanzeige verwenden.
- Bedienung waehrend der Fahrt vermeiden.
- Pi, Kabel und OBD Adapter sicher montieren.
