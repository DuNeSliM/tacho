# Raspberry Pi als Zwischenserver (OBD + Handy)

## Empfohlene Topologie
- `wlan0` (intern): verbindet sich mit dem OBD2-WiFi Adapter.
- `wlan1` (USB WiFi Dongle): erstellt ein eigenes Hotspot-Netz fuer dein Handy.

Hinweis: Mit nur einem WLAN-Interface ist `STA + AP` parallel oft instabil oder gar nicht moeglich. Fuer ein sauberes Setup ist ein zweiter USB-WiFi Adapter die robuste Variante.

## 1) wlan0 mit OBD Adapter verbinden

Datei `wpa_supplicant.conf` anpassen:

```conf
country=DE
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1

network={
    ssid="DEIN_OBD_WIFI_NAME"
    psk="DEIN_OBD_WIFI_PASSWORT"
    key_mgmt=WPA-PSK
}
```

Falls dein OBD Adapter ein offenes Netz ist, kann `key_mgmt=NONE` noetig sein.

## 2) wlan1 als Hotspot vorbereiten

Pakete installieren:

```bash
sudo apt update
sudo apt install -y hostapd dnsmasq
sudo systemctl stop hostapd dnsmasq
```

In `/etc/dhcpcd.conf` anhaengen:

```conf
interface wlan1
static ip_address=192.168.50.1/24
nohook wpa_supplicant
```

`/etc/hostapd/hostapd.conf`:

```conf
interface=wlan1
driver=nl80211
ssid=PiDash
hw_mode=g
channel=6
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=ChangeThisPass123
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
```

`/etc/default/hostapd`:

```conf
DAEMON_CONF="/etc/hostapd/hostapd.conf"
```

`/etc/dnsmasq.conf` (alte Datei vorher sichern):

```conf
interface=wlan1
dhcp-range=192.168.50.10,192.168.50.200,255.255.255.0,24h
```

Services starten:

```bash
sudo systemctl unmask hostapd
sudo systemctl enable --now hostapd dnsmasq
sudo systemctl restart dhcpcd
```

## 3) Dashboard erreichbar machen

- Pi startet die App auf Port `8080`.
- Handy verbindet sich mit WLAN `PiDash`.
- Dann im Handy-Browser aufrufen: `http://192.168.50.1:8080`

## 4) Pruefen

```bash
ip a show wlan0
ip a show wlan1
systemctl status hostapd dnsmasq
curl http://127.0.0.1:8080/api/health
```

