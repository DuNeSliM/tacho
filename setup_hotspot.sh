#!/bin/bash
# Setup script for Pi 3 WiFi Hotspot (AP+STA mode)
# The Pi stays connected to the OBD-II WiFi AND creates its own hotspot.
#
# Run once: sudo bash setup_hotspot.sh

set -e

echo "=== Installing required packages ==="
sudo apt update
sudo apt install -y hostapd dnsmasq

echo "=== Stopping services during setup ==="
sudo systemctl stop hostapd 2>/dev/null || true
sudo systemctl stop dnsmasq 2>/dev/null || true

echo "=== Creating virtual AP interface (uap0) ==="
# Add uap0 creation at boot
cat > /etc/systemd/system/uap0.service << 'EOF'
[Unit]
Description=Create uap0 virtual AP interface
Before=hostapd.service
Before=dnsmasq.service
After=network-pre.target

[Service]
Type=oneshot
ExecStart=/sbin/iw dev wlan0 interface add uap0 type __ap
ExecStartPost=/bin/ip link set uap0 up
ExecStartPost=/bin/ip addr add 192.168.4.1/24 dev uap0
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

echo "=== Configuring hostapd (WiFi hotspot) ==="
cat > /etc/hostapd/hostapd.conf << 'EOF'
interface=uap0
driver=nl80211
ssid=PiDash-OBD
hw_mode=g
channel=6
wmm_enabled=0
auth_algs=1
wpa=0
EOF

# Point hostapd to our config
sed -i 's|^#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd 2>/dev/null || true

echo "=== Configuring dnsmasq (DHCP for hotspot clients) ==="
# Backup original config
if [ -f /etc/dnsmasq.conf ] && [ ! -f /etc/dnsmasq.conf.bak ]; then
    cp /etc/dnsmasq.conf /etc/dnsmasq.conf.bak
fi

cat > /etc/dnsmasq.d/hotspot.conf << 'EOF'
interface=uap0
bind-interfaces
dhcp-range=192.168.4.10,192.168.4.50,255.255.255.0,24h
EOF

echo "=== Enabling services ==="
sudo systemctl unmask hostapd
sudo systemctl daemon-reload
sudo systemctl enable uap0.service
sudo systemctl enable hostapd
sudo systemctl enable dnsmasq

echo "=== Starting services ==="
# Create the interface now
sudo iw dev wlan0 interface add uap0 type __ap 2>/dev/null || true
sudo ip link set uap0 up 2>/dev/null || true
sudo ip addr add 192.168.4.1/24 dev uap0 2>/dev/null || true

sudo systemctl start hostapd
sudo systemctl start dnsmasq

echo ""
echo "============================================="
echo "  Hotspot ready!"
echo "  SSID: PiDash-OBD (open, no password)"
echo "  IP:   192.168.4.1"
echo "============================================="
echo ""
echo "Phone OBD apps connect to: 192.168.4.1:35000"
echo "Reboot to verify everything starts automatically."
