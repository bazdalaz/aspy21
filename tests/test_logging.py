import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.aspy21 import configure_logging
from src.aspy21.client import logger


def test_configure_logging_with_level():
    """Test configure_logging with explicit level."""
    configure_logging("DEBUG")
    assert logger.level == logging.DEBUG
    assert len(logger.handlers) > 0


def test_configure_logging_from_env(monkeypatch):
    """Test configure_logging reads from environment variable."""
    monkeypatch.setenv("ASPEN_LOG_LEVEL", "ERROR")
    configure_logging()
    assert logger.level == logging.ERROR


def test_configure_logging_default(monkeypatch):
    """Test configure_logging uses WARNING as default."""
    monkeypatch.delenv("ASPEN_LOG_LEVEL", raising=False)
    # Clear existing handlers to test fresh
    logger.handlers.clear()
    configure_logging()
    assert logger.level == logging.WARNING


def test_configure_logging_handler_format():
    """Test that handler has correct format."""
    logger.handlers.clear()
    configure_logging("INFO")

    assert len(logger.handlers) == 1
    handler = logger.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.formatter is not None
    # Type narrowing: formatter._fmt could be None, check it
    fmt = handler.formatter._fmt
    assert fmt is not None
    assert "%(asctime)s" in fmt
    assert "%(name)s" in fmt
    assert "%(levelname)s" in fmt
