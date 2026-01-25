"""Structured logging utilities for tchu-tchu."""

from celery_salt.logging.formatters import CelerySaltFormatter
from celery_salt.logging.handlers import get_logger

# Backward compatibility alias
TchuFormatter = CelerySaltFormatter

__all__ = ["CelerySaltFormatter", "TchuFormatter", "get_logger"]
