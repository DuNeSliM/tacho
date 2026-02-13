from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _load_local_env_file() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        normalized_key = key.strip()
        normalized_value = value.strip().strip('"').strip("'")
        os.environ.setdefault(normalized_key, normalized_value)


def _read_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _read_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    obd_host: str
    obd_port: int
    poll_interval: float
    reconnect_delay: float
    http_host: str
    http_port: int
    simulate: bool


def load_settings() -> Settings:
    _load_local_env_file()
    return Settings(
        obd_host=os.getenv("OBD_HOST", "192.168.0.10"),
        obd_port=_read_int("OBD_PORT", 35000),
        poll_interval=_read_float("POLL_INTERVAL", 0.40),
        reconnect_delay=_read_float("RECONNECT_DELAY", 3.0),
        http_host=os.getenv("HTTP_HOST", "0.0.0.0"),
        http_port=_read_int("HTTP_PORT", 8080),
        simulate=_read_bool("SIMULATE", False),
    )
