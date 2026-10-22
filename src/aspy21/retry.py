"""Retrying of transient HTTP failures."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Server responses that usually succeed when repeated. 500 is left out: it reports a
# server-side failure, which repeating the same request rarely fixes.
RETRY_STATUS_CODES = frozenset({429, 502, 503, 504})

# Network failures that usually succeed when repeated. Read timeouts are left out: a query
# slow enough to time out is likely to time out again, and repeating it adds server load.
RETRY_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)

BACKOFF_INITIAL = 0.5  # seconds before the first retry; doubles on each retry
BACKOFF_MAX = 8.0  # longest wait between retries
RETRY_AFTER_MAX = 30.0  # longest wait honored from a Retry-After header

_backoff = wait_exponential(multiplier=BACKOFF_INITIAL, min=BACKOFF_INITIAL, max=BACKOFF_MAX)


def _sleep(seconds: float) -> None:
    """Wait between attempts (replaced in tests)."""
    time.sleep(seconds)


def _is_transient(exc: BaseException) -> bool:
    """Return True if a failed request is worth repeating."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRY_STATUS_CODES
    return isinstance(exc, RETRY_EXCEPTIONS)


def _retry_after(exc: BaseException | None) -> float | None:
    """Return the wait in seconds requested by a Retry-After header, if any."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    value = exc.response.headers.get("Retry-After", "")
    try:
        seconds = float(value)
    except ValueError:
        # HTTP-date values are rare for these responses; fall back to backoff
        return None
    return min(max(seconds, 0.0), RETRY_AFTER_MAX)


def _wait(state: RetryCallState) -> float:
    """Wait as long as the server asked, otherwise back off exponentially."""
    exc = state.outcome.exception() if state.outcome else None
    retry_after = _retry_after(exc)
    return retry_after if retry_after is not None else _backoff(state)


def _log_retry(state: RetryCallState) -> None:
    exc = state.outcome.exception() if state.outcome else None
    wait = state.next_action.sleep if state.next_action else 0.0
    reason = (
        f"HTTP {exc.response.status_code}"
        if isinstance(exc, httpx.HTTPStatusError)
        else type(exc).__name__
    )
    logger.warning(f"Request failed ({reason}), retry {state.attempt_number} in {wait:.1f}s")


def send(
    client: httpx.Client, method: str, url: str, *, retries: int, **kwargs: Any
) -> httpx.Response:
    """Send a request, repeating it after transient failures.

    Args:
        client: HTTP client to send the request with
        method: HTTP method, e.g. "GET" or "POST"
        url: Request URL
        retries: How many times to repeat a request that failed transiently (0 = never)
        **kwargs: Passed to httpx.Client.request()

    Returns:
        A successful (2xx/3xx) response

    Raises:
        httpx.HTTPStatusError: For an error response, after any retries
        httpx.RequestError: For a failed request, after any retries
    """

    def attempt() -> httpx.Response:
        response = client.request(method, url, **kwargs)
        response.raise_for_status()
        return response

    retrying = Retrying(
        stop=stop_after_attempt(retries + 1),
        wait=_wait,
        retry=retry_if_exception(_is_transient),
        before_sleep=_log_retry,
        sleep=lambda seconds: _sleep(seconds),
        reraise=True,
    )
    return retrying(attempt)
