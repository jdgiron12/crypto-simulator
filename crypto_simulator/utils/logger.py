"""Logging setup for the Crypto Market Simulator."""

from __future__ import annotations

import logging

from crypto_simulator.config.settings import LoggingSettings


def configure_logging(settings: LoggingSettings) -> None:
    """Configure the root logger once, at application startup."""
    logging.basicConfig(level=settings.level, format=settings.format)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
