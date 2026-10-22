import logging

import httpx
import pytest
import respx

from aspy21 import AspenClient, configure_logging

BASE_URL = "https://aspen.local/ProcessData/AtProcessDataREST.dll"


@pytest.fixture
def package_logger():
    """The aspy21 package logger, restored after the test."""
    logger = logging.getLogger("aspy21")
    level, handlers = logger.level, logger.handlers[:]
    logger.handlers.clear()
    yield logger
    logger.handlers[:] = handlers
    logger.setLevel(level)


def test_configure_logging_with_level(package_logger):
    """Test configure_logging with explicit level."""
    configure_logging("DEBUG")
    assert package_logger.level == logging.DEBUG
    assert len(package_logger.handlers) > 0


def test_configure_logging_from_env(package_logger, monkeypatch):
    """Test configure_logging reads from environment variable."""
    monkeypatch.setenv("ASPEN_LOG_LEVEL", "ERROR")
    configure_logging()
    assert package_logger.level == logging.ERROR


def test_configure_logging_default(package_logger, monkeypatch):
    """Test configure_logging uses WARNING as default."""
    monkeypatch.delenv("ASPEN_LOG_LEVEL", raising=False)
    configure_logging()
    assert package_logger.level == logging.WARNING


def test_configure_logging_handler_format(package_logger):
    """Test that handler has correct format."""
    configure_logging("INFO")

    assert len(package_logger.handlers) == 1
    handler = package_logger.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.formatter is not None
    # Type narrowing: formatter._fmt could be None, check it
    fmt = handler.formatter._fmt
    assert fmt is not None
    assert "%(asctime)s" in fmt
    assert "%(name)s" in fmt
    assert "%(levelname)s" in fmt


def test_configure_logging_twice_adds_one_handler(package_logger):
    configure_logging("INFO")
    configure_logging("DEBUG")
    assert len(package_logger.handlers) == 1
    assert package_logger.level == logging.DEBUG


@pytest.mark.parametrize(
    "module",
    ["aspy21.client", "aspy21.retry", "aspy21.cache", "aspy21.readers.snapshot_reader"],
)
@pytest.mark.usefixtures("package_logger")
def test_level_applies_to_every_module(module):
    configure_logging("DEBUG")
    assert logging.getLogger(module).getEffectiveLevel() == logging.DEBUG

    configure_logging("ERROR")
    assert not logging.getLogger(module).isEnabledFor(logging.WARNING)


@pytest.mark.usefixtures("package_logger")
def test_module_messages_use_configured_format(capsys):
    """Messages from modules other than the client are formatted, not bare."""
    configure_logging("DEBUG")
    logging.getLogger("aspy21.readers.snapshot_reader").warning("no data")

    err = capsys.readouterr().err
    assert " - aspy21.readers.snapshot_reader - WARNING - no data" in err


@pytest.mark.usefixtures("package_logger")
@respx.mock
def test_retry_warnings_follow_configured_level(capsys):
    """With level ERROR, retry warnings are not printed."""
    configure_logging("ERROR")
    respx.post(f"{BASE_URL}/SQL").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=[])]
    )
    with AspenClient(BASE_URL, datasource="IP21") as client:
        client.read(["TAG1"])

    assert "Request failed" not in capsys.readouterr().err


@pytest.mark.usefixtures("package_logger")
@respx.mock
def test_retry_warnings_shown_at_warning_level(capsys):
    configure_logging("WARNING")
    respx.post(f"{BASE_URL}/SQL").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=[])]
    )
    with AspenClient(BASE_URL, datasource="IP21") as client:
        client.read(["TAG1"])

    assert " - aspy21.retry - WARNING - Request failed (HTTP 503)" in capsys.readouterr().err


def test_config_log_for_own_http_client(caplog):
    with caplog.at_level(logging.DEBUG, logger="aspy21.client"):
        AspenClient(BASE_URL, datasource="IP21", timeout=12, verify_ssl=False).close()

    assert "Config: timeout=12s, verify_ssl=False, datasource=IP21, retries=2" in caplog.text


def test_config_log_for_provided_http_client(caplog):
    """The client's own timeout is logged; ignored timeout/verify_ssl arguments are not."""
    with httpx.Client(timeout=60) as http, caplog.at_level(logging.DEBUG, logger="aspy21.client"):
        AspenClient(BASE_URL, datasource="IP21", http_client=http, timeout=12, retries=0)

    assert "Config: provided http_client (timeout=60s), datasource=IP21, retries=0" in (caplog.text)
    assert "verify_ssl" not in caplog.text
    assert "timeout=12" not in caplog.text
