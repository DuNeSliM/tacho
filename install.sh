#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"
SERVICE_DIR="/etc/systemd/system"
PIDASH_SERVICE="${SERVICE_DIR}/pidash.service"
KIOSK_SERVICE="${SERVICE_DIR}/pidash-kiosk.service"

if [[ "${EUID}" -eq 0 ]]; then
    APP_USER="${SUDO_USER:-${INSTALL_USER:-pi}}"
else
    APP_USER="${USER}"
fi

if ! id "${APP_USER}" >/dev/null 2>&1; then
    echo "User '${APP_USER}' does not exist. Set INSTALL_USER=<user> and rerun."
    exit 1
fi

APP_HOME="$(getent passwd "${APP_USER}" | cut -d: -f6)"
if [[ -z "${APP_HOME}" ]]; then
    echo "Could not resolve home directory for user '${APP_USER}'."
    exit 1
fi

as_root() {
    if [[ "${EUID}" -eq 0 ]]; then
        "$@"
    else
        sudo "$@"
    fi
}

echo "[1/7] Installing OS packages..."
as_root apt-get update
as_root apt-get install -y git python3-venv python3-pip curl xserver-xorg xinit openbox
if ! as_root apt-get install -y chromium; then
    as_root apt-get install -y chromium-browser
fi

echo "[2/7] Creating virtual environment..."
python3 -m venv "${VENV_DIR}"

echo "[3/7] Installing Python dependencies..."
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${PROJECT_DIR}/requirements.txt"

echo "[4/7] Ensuring .env exists..."
if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
    if [[ -f "${PROJECT_DIR}/.env.example" ]]; then
        cp "${PROJECT_DIR}/.env.example" "${PROJECT_DIR}/.env"
    else
        cat > "${PROJECT_DIR}/.env" <<'EOF'
OBD_HOST=192.168.0.10
OBD_PORT=35000
POLL_INTERVAL=0.40
RECONNECT_DELAY=3.0
HTTP_HOST=0.0.0.0
HTTP_PORT=8080
SIMULATE=false
EOF
    fi
fi

echo "[5/7] Making kiosk script executable..."
chmod +x "${PROJECT_DIR}/scripts/start-kiosk.sh"

echo "[6/7] Installing systemd services..."
TMP_PIDASH="$(mktemp)"
TMP_KIOSK="$(mktemp)"
trap 'rm -f "${TMP_PIDASH}" "${TMP_KIOSK}"' EXIT

cat > "${TMP_PIDASH}" <<EOF
[Unit]
Description=Pi Digital Dashboard Gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${PROJECT_DIR}/.env
ExecStart=${VENV_DIR}/bin/python ${PROJECT_DIR}/run.py
Restart=always
RestartSec=2
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

cat > "${TMP_KIOSK}" <<EOF
[Unit]
Description=Pi Dashboard Kiosk Screen
After=pidash.service systemd-user-sessions.service
Requires=pidash.service
Conflicts=getty@tty1.service

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${PROJECT_DIR}
Environment=HOME=${APP_HOME}
Environment=DASH_URL=http://127.0.0.1:8080
ExecStart=${PROJECT_DIR}/scripts/start-kiosk.sh
Restart=always
RestartSec=2
StandardInput=tty
TTYPath=/dev/tty1
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

as_root install -m 644 "${TMP_PIDASH}" "${PIDASH_SERVICE}"
as_root install -m 644 "${TMP_KIOSK}" "${KIOSK_SERVICE}"

echo "[7/7] Enabling and starting services..."
as_root systemctl daemon-reload
as_root systemctl enable pidash pidash-kiosk
as_root systemctl restart pidash pidash-kiosk

echo
echo "Install completed."
echo "Edit ${PROJECT_DIR}/.env with your OBD adapter settings if needed."
echo "Check status with:"
echo "  systemctl status pidash --no-pager"
echo "  systemctl status pidash-kiosk --no-pager"
echo
echo "Note: phone hotspot setup (wlan1 + hostapd/dnsmasq) is documented in docs/network_setup.md."
