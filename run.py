from __future__ import annotations

import logging

import uvicorn

from app.config import load_settings


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


if __name__ == "__main__":
    configure_logging()
    settings = load_settings()
    uvicorn.run(
        "app.server:app",
        host=settings.http_host,
        port=settings.http_port,
        log_level="info",
    )
