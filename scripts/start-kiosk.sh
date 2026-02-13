#!/usr/bin/env bash
set -euo pipefail

URL="${DASH_URL:-http://127.0.0.1:8080}"

if command -v chromium >/dev/null 2>&1; then
    BROWSER_BIN="$(command -v chromium)"
elif command -v chromium-browser >/dev/null 2>&1; then
    BROWSER_BIN="$(command -v chromium-browser)"
else
    echo "Chromium not found. Install with: sudo apt install -y chromium-browser"
    exit 1
fi

# Wait until local API is reachable, then open the dashboard in kiosk mode.
for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:8080/api/health" >/dev/null; then
        break
    fi
    sleep 1
done

exec xinit "$BROWSER_BIN" \
    --kiosk "$URL" \
    --incognito \
    --noerrdialogs \
    --disable-translate \
    --disable-infobars \
    --check-for-update-interval=31536000 \
    --autoplay-policy=no-user-gesture-required \
    --overscroll-history-navigation=0 \
    --disable-session-crashed-bubble \
    --disable-features=TranslateUI \
    --window-size=1280,720 \
    --window-position=0,0 \
    -- :0 vt1 -nocursor

