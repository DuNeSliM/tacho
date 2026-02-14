# Raspberry Pi as OBD + Phone Gateway

## Goal

- `wlan0` connects to the OBD2 adapter WiFi.
- `wlan1` (USB WiFi dongle) creates a hotspot for your phone.
- Phone opens `http://192.168.50.1:8080` to see live dashboard data.

Using only one WiFi interface for both client mode (OBD) and access point mode (phone) is usually unstable on Pi 3. A second USB WiFi adapter is the reliable setup.

## 1) Connect wlan0 to OBD adapter

Edit `/etc/wpa_supplicant/wpa_supplicant.conf`:

```conf
country=US
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1

network={
    ssid="YOUR_OBD_WIFI_NAME"
    psk="YOUR_OBD_WIFI_PASSWORD"
    key_mgmt=WPA-PSK
}
```

If your adapter is open (no password), use:

```conf
network={
    ssid="YOUR_OBD_WIFI_NAME"
    key_mgmt=NONE
}
```

## 2) Configure wlan1 as hotspot

Install packages:

```bash
sudo apt update
sudo apt install -y hostapd dnsmasq
sudo systemctl stop hostapd dnsmasq
```

Append to `/etc/dhcpcd.conf`:

```conf
interface wlan1
static ip_address=192.168.50.1/24
nohook wpa_supplicant
```

Create `/etc/hostapd/hostapd.conf`:

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

Edit `/etc/default/hostapd`:

```conf
DAEMON_CONF="/etc/hostapd/hostapd.conf"
```

Replace `/etc/dnsmasq.conf` content:

```conf
interface=wlan1
dhcp-range=192.168.50.10,192.168.50.200,255.255.255.0,24h
```

Enable and start services:

```bash
sudo systemctl unmask hostapd
sudo systemctl enable --now hostapd dnsmasq
sudo systemctl restart dhcpcd
```

## 3) Verify

```bash
ip a show wlan0
ip a show wlan1
systemctl status hostapd dnsmasq --no-pager
curl http://127.0.0.1:8080/api/health
```

## 4) Phone access

- Connect phone to `PiDash` hotspot.
- Open `http://192.168.50.1:8080`
