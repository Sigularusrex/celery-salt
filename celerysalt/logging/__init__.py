"""Structured logging utilities for tchu-tchu."""

from celerysalt.logging.formatters import CelerySaltFormatter
from celerysalt.logging.handlers import get_logger

# Backward compatibility alias
TchuFormatter = CelerySaltFormatter

__all__ = ["CelerySaltFormatter", "TchuFormatter", "get_logger"]
