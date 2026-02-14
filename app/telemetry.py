from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import math
import random
import re
from typing import Callable

from .config import Settings

LOGGER = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass(frozen=True)
class PIDDefinition:
    command: str
    bytes_needed: int
    decoder: Callable[[list[int]], float]


PID_TABLE: dict[str, PIDDefinition] = {
    "rpm": PIDDefinition("010C", 2, lambda d: ((d[0] * 256) + d[1]) / 4.0),
    "speed_kmh": PIDDefinition("010D", 1, lambda d: float(d[0])),
    "coolant_c": PIDDefinition("0105", 1, lambda d: float(d[0] - 40)),
    "throttle_pct": PIDDefinition("0111", 1, lambda d: (d[0] * 100.0) / 255.0),
    "engine_load_pct": PIDDefinition("0104", 1, lambda d: (d[0] * 100.0) / 255.0),
    "fuel_level_pct": PIDDefinition("012F", 1, lambda d: (d[0] * 100.0) / 255.0),
    "intake_c": PIDDefinition("010F", 1, lambda d: float(d[0] - 40)),
}

CONTROL_LINES = {
    "OK",
    "NO DATA",
    "STOPPED",
    "UNABLE TO CONNECT",
    "BUS INIT...ERROR",
    "ERROR",
    "?",
}
HEX_LINE_RE = re.compile(r"^[0-9A-F ]+$")
VOLT_RE = re.compile(r"(\d{1,2}(?:[.,]\d{1,2})?)")


class TelemetryStore:
    def __init__(self, adapter_host: str, adapter_port: int) -> None:
        self._lock = asyncio.Lock()
        self._snapshot: dict[str, object] = {
            "connected": False,
            "updated_at": None,
            "last_error": None,
            "adapter": {
                "host": adapter_host,
                "port": adapter_port,
            },
            "metrics": {key: None for key in PID_TABLE} | {"battery_v": None},
        }

    async def set_connected(self, connected: bool, last_error: str | None = None) -> None:
        async with self._lock:
            self._snapshot["connected"] = connected
            self._snapshot["last_error"] = last_error
            self._snapshot["updated_at"] = utc_now_iso()

    async def update_metrics(
        self,
        metrics: dict[str, float | None],
        connected: bool = True,
        last_error: str | None = None,
    ) -> None:
        async with self._lock:
            metric_store = self._snapshot["metrics"]
            assert isinstance(metric_store, dict)
            for key, value in metrics.items():
                if key in metric_store:
                    metric_store[key] = value
            self._snapshot["connected"] = connected
            self._snapshot["last_error"] = last_error
            self._snapshot["updated_at"] = utc_now_iso()

    async def snapshot(self) -> dict[str, object]:
        async with self._lock:
            return copy.deepcopy(self._snapshot)


class ELM327Client:
    def __init__(self, host: str, port: int, timeout: float = 3.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port),
            timeout=self._timeout,
        )
        await self._synchronize_prompt()
        await self._initialize_adapter()

    async def close(self) -> None:
        if self._writer is None:
            return
        self._writer.close()
        await self._writer.wait_closed()
        self._reader = None
        self._writer = None

    async def send(self, command: str) -> str:
        if self._writer is None:
            raise ConnectionError("OBD adapter socket is not connected.")

        payload = f"{command}\r".encode("ascii")
        self._writer.write(payload)
        await self._writer.drain()
        return await self._read_until_prompt()

    async def _initialize_adapter(self) -> None:
        setup_commands = ("ATZ", "ATE0", "ATL0", "ATS0", "ATH0", "ATSP0")
        for cmd in setup_commands:
            await self.send(cmd)
            await asyncio.sleep(0.05)

    async def _synchronize_prompt(self) -> None:
        if self._writer is None:
            raise ConnectionError("OBD adapter socket is not connected.")

        # Clear stale bytes/prompt before normal requests begin.
        for _ in range(2):
            self._writer.write(b"\r")
            await self._writer.drain()
            try:
                await self._read_until_prompt()
            except Exception:
                return

    async def _read_until_prompt(self) -> str:
        if self._reader is None:
            raise ConnectionError("OBD adapter socket is not connected.")

        chunks: list[str] = []
        while True:
            raw = await asyncio.wait_for(self._reader.read(256), timeout=self._timeout)
            if not raw:
                raise ConnectionError("OBD adapter closed the socket.")
            text = raw.decode("ascii", errors="ignore")
            chunks.append(text)
            if ">" in text:
                break
        return "".join(chunks)


def _split_hex_pairs(value: str) -> list[str]:
    compact = value.replace(" ", "")
    if len(compact) % 2 != 0:
        return []
    return [compact[i : i + 2] for i in range(0, len(compact), 2)]


def parse_pid_bytes(command: str, response: str) -> list[int] | None:
    expected_mode = f"{int(command[:2], 16) + 0x40:02X}"
    expected_pid = command[2:4].upper()
    command_upper = command.upper()

    for raw_line in response.replace("\r", "\n").split("\n"):
        line = raw_line.strip().upper().replace(">", "")
        if not line or line == command_upper or line.startswith("SEARCHING"):
            continue
        if line in CONTROL_LINES:
            continue
        if not HEX_LINE_RE.fullmatch(line):
            continue

        tokens = line.split() if " " in line else _split_hex_pairs(line)
        if len(tokens) < 2:
            continue
        if tokens[0] != expected_mode or tokens[1] != expected_pid:
            continue

        try:
            return [int(token, 16) for token in tokens[2:]]
        except ValueError:
            continue
    return None


def parse_voltage(response: str) -> float | None:
    match = VOLT_RE.search(response)
    if match is None:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


async def _wait_or_stop(stop_event: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        return


class TelemetryPoller:
    def __init__(self, settings: Settings, store: TelemetryStore) -> None:
        self._settings = settings
        self._store = store

    async def run(self, stop_event: asyncio.Event) -> None:
        if self._settings.simulate:
            await self._run_simulation(stop_event)
            return
        await self._run_obd(stop_event)

    async def _run_obd(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            client = ELM327Client(self._settings.obd_host, self._settings.obd_port)
            try:
                LOGGER.info(
                    "Connecting to OBD adapter %s:%s",
                    self._settings.obd_host,
                    self._settings.obd_port,
                )
                await client.connect()
                await self._store.set_connected(True, None)

                while not stop_event.is_set():
                    metrics: dict[str, float | None] = {}
                    for key, definition in PID_TABLE.items():
                        response = await client.send(definition.command)
                        payload = parse_pid_bytes(definition.command, response)
                        if payload is None or len(payload) < definition.bytes_needed:
                            metrics[key] = None
                            continue

                        raw_value = definition.decoder(payload[: definition.bytes_needed])
                        metrics[key] = round(raw_value, 1)

                    voltage_response = await client.send("ATRV")
                    voltage_value = parse_voltage(voltage_response)
                    metrics["battery_v"] = round(voltage_value, 2) if voltage_value is not None else None

                    await self._store.update_metrics(metrics, connected=True, last_error=None)
                    await _wait_or_stop(stop_event, self._settings.poll_interval)
            except Exception as exc:
                LOGGER.warning("OBD polling failed: %s", exc)
                await self._store.set_connected(False, str(exc))
                await _wait_or_stop(stop_event, self._settings.reconnect_delay)
            finally:
                await client.close()

    async def _run_simulation(self, stop_event: asyncio.Event) -> None:
        await self._store.set_connected(True, None)
        t = 0.0

        while not stop_event.is_set():
            t += 0.15
            speed = max(0.0, min(220.0, 70.0 + math.sin(t) * 45.0 + random.uniform(-2.5, 2.5)))
            rpm = max(700.0, min(7000.0, 900.0 + speed * 34.0 + random.uniform(-70.0, 70.0)))
            load = max(4.0, min(100.0, (rpm / 7000.0) * 100.0 + random.uniform(-4.0, 4.0)))
            throttle = max(2.0, min(100.0, (speed / 220.0) * 90.0 + random.uniform(-3.5, 3.5)))
            coolant = max(65.0, min(110.0, 88.0 + math.sin(t * 0.2) * 6.0 + random.uniform(-0.6, 0.6)))
            intake = max(10.0, min(55.0, 25.0 + math.sin(t * 0.4) * 9.0 + random.uniform(-1.5, 1.5)))
            fuel = max(5.0, min(100.0, 78.0 - (t * 0.05)))
            voltage = max(12.1, min(14.4, 13.2 + math.sin(t * 0.35) * 0.5))

            await self._store.update_metrics(
                {
                    "speed_kmh": round(speed, 1),
                    "rpm": round(rpm, 1),
                    "engine_load_pct": round(load, 1),
                    "throttle_pct": round(throttle, 1),
                    "coolant_c": round(coolant, 1),
                    "intake_c": round(intake, 1),
                    "fuel_level_pct": round(fuel, 1),
                    "battery_v": round(voltage, 2),
                },
                connected=True,
                last_error=None,
            )
            await _wait_or_stop(stop_event, self._settings.poll_interval)
