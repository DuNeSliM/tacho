const view = {
    pill: document.getElementById("connection-pill"),
    updatedAt: document.getElementById("updated-at"),
    adapterInfo: document.getElementById("adapter-info"),
    errorInfo: document.getElementById("error-info"),
    speed: document.getElementById("speed-value"),
    rpm: document.getElementById("rpm-value"),
    coolant: document.getElementById("coolant-value"),
    intake: document.getElementById("intake-value"),
    throttle: document.getElementById("throttle-value"),
    load: document.getElementById("load-value"),
    fuel: document.getElementById("fuel-value"),
    battery: document.getElementById("battery-value"),
    bars: {
        speed: document.getElementById("speed-bar"),
        rpm: document.getElementById("rpm-bar"),
        coolant: document.getElementById("coolant-bar"),
        intake: document.getElementById("intake-bar"),
        throttle: document.getElementById("throttle-bar"),
        load: document.getElementById("load-bar"),
        fuel: document.getElementById("fuel-bar"),
        battery: document.getElementById("battery-bar"),
    },
};

const limits = {
    speed_kmh: 220,
    rpm: 7000,
    coolant_c: 120,
    intake_c: 80,
    throttle_pct: 100,
    engine_load_pct: 100,
    fuel_level_pct: 100,
    battery_v: 16,
};

let requestInFlight = false;

function formatValue(value, digits = 0) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return "--";
    }
    return Number(value).toFixed(digits);
}

function setBar(element, value, max) {
    if (!element || value === null || value === undefined || Number.isNaN(Number(value))) {
        if (element) {
            element.style.width = "0%";
        }
        return;
    }

    const ratio = Math.max(0, Math.min(1, Number(value) / max));
    element.style.width = `${(ratio * 100).toFixed(1)}%`;
}

function formatTimestamp(isoValue) {
    if (!isoValue) {
        return "No data yet";
    }

    const parsed = new Date(isoValue);
    if (Number.isNaN(parsed.getTime())) {
        return "No data yet";
    }

    const local = parsed.toLocaleTimeString([], { hour12: false });
    return `Update ${local}`;
}

function setConnectionState(connected) {
    if (connected) {
        view.pill.textContent = "Online";
        view.pill.classList.remove("offline");
        view.pill.classList.add("online");
        return;
    }

    view.pill.textContent = "Offline";
    view.pill.classList.remove("online");
    view.pill.classList.add("offline");
}

function renderSnapshot(snapshot) {
    const metrics = snapshot.metrics || {};
    const connected = Boolean(snapshot.connected);

    setConnectionState(connected);
    view.updatedAt.textContent = formatTimestamp(snapshot.updated_at);

    const adapter = snapshot.adapter || {};
    view.adapterInfo.textContent = `Adapter: ${adapter.host || "-"}:${adapter.port || "-"}`;
    view.errorInfo.textContent = snapshot.last_error
        ? `Error: ${snapshot.last_error}`
        : "Status: data stream active";

    view.speed.textContent = formatValue(metrics.speed_kmh, 0);
    view.rpm.textContent = formatValue(metrics.rpm, 0);
    view.coolant.textContent = formatValue(metrics.coolant_c, 0);
    view.intake.textContent = formatValue(metrics.intake_c, 0);
    view.throttle.textContent = formatValue(metrics.throttle_pct, 0);
    view.load.textContent = formatValue(metrics.engine_load_pct, 0);
    view.fuel.textContent = formatValue(metrics.fuel_level_pct, 0);
    view.battery.textContent = formatValue(metrics.battery_v, 2);

    setBar(view.bars.speed, metrics.speed_kmh, limits.speed_kmh);
    setBar(view.bars.rpm, metrics.rpm, limits.rpm);
    setBar(view.bars.coolant, metrics.coolant_c, limits.coolant_c);
    setBar(view.bars.intake, metrics.intake_c, limits.intake_c);
    setBar(view.bars.throttle, metrics.throttle_pct, limits.throttle_pct);
    setBar(view.bars.load, metrics.engine_load_pct, limits.engine_load_pct);
    setBar(view.bars.fuel, metrics.fuel_level_pct, limits.fuel_level_pct);
    setBar(view.bars.battery, metrics.battery_v, limits.battery_v);
}

async function tick() {
    if (requestInFlight) {
        return;
    }
    requestInFlight = true;

    try {
        const response = await fetch("/api/state", { cache: "no-store" });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const snapshot = await response.json();
        renderSnapshot(snapshot);
    } catch (error) {
        setConnectionState(false);
        view.updatedAt.textContent = "No connection to server";
        view.errorInfo.textContent = `Error: ${error.message}`;
    } finally {
        requestInFlight = false;
    }
}

tick();
setInterval(tick, 450);
