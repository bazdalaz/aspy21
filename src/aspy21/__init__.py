"""
aspy21 - Modern Python client for Aspen InfoPlus.21 (IP.21).

A high-performance REST API client for accessing Aspen process data
with pandas DataFrame output and flexible batching.
"""

from .client import AspenClient, configure_logging
from .models import ReaderType

try:
    from ._version import __version__  # type: ignore[import-not-found]
except ImportError:
    # Development mode - no version file generated yet
    __version__ = "0.0.0.dev0"

__all__ = ["AspenClient", "ReaderType", "configure_logging", "__version__"]
