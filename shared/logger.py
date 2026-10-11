"""Small logging factory shared by CLI and service entry points."""

from __future__ import annotations

import logging


def get_logger(module_name: str) -> logging.Logger:
    """Return a consistently named logger without configuring global handlers."""

    return logging.getLogger(module_name)


__all__ = ["get_logger"]
