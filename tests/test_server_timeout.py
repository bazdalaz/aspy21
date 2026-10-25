"""Tests for the query timeout sent to IP.21 (the to="..." attribute of SQL requests).

The server is given as long as the HTTP client waits, so AspenClient(timeout=120) lets a
slow query run for 120 seconds instead of being stopped by the server after 30.
"""

from __future__ import annotations

import re

import httpx
import pytest

from aspy21 import AspenClient, IncludeFields, ReaderType
from aspy21.query_builder import server_timeout

BASE_URL = "https://aspen.local/ProcessData/AtProcessDataREST.dll"


@pytest.mark.parametrize(
    ("read_timeout", "expected"),
    [(30.0, 30), (120, 120), (45.5, 46), (0.2, 1), (None, 30)],
)
def test_server_timeout(read_timeout, expected):
    assert server_timeout(read_timeout) == expected


def sent_timeouts(mock_api, client: AspenClient) -> list[int]:
    """Run a history read, a snapshot read and a description search; return their to=."""
    route = mock_api.post(f"{BASE_URL}/SQL").mock(return_value=httpx.Response(200, json=[]))
    with client:
        client.read(["T1"], start="2025-01-01 00:00:00", end="2025-01-01 01:00:00")
        client.read(["T1"], read_type=ReaderType.SNAPSHOT)
        client.search("T*", description="temp", include=IncludeFields.DESCRIPTION)
    return [
        int(re.search(r' to="(\d+)"', call.request.content.decode()).group(1))  # type: ignore[union-attr]
        for call in route.calls
    ]


def test_default_timeout_unchanged(mock_api):
    assert sent_timeouts(mock_api, AspenClient(BASE_URL, datasource="IP21")) == [30, 30, 30]


def test_client_timeout_sent_to_server(mock_api):
    client = AspenClient(BASE_URL, datasource="IP21", timeout=120)

    assert sent_timeouts(mock_api, client) == [120, 120, 120]


def test_provided_http_client_timeout_sent_to_server(mock_api):
    http = httpx.Client(timeout=httpx.Timeout(10, read=75))
    client = AspenClient(BASE_URL, datasource="IP21", http_client=http)

    assert sent_timeouts(mock_api, client) == [75, 75, 75]
