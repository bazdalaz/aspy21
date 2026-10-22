"""Tests for Browse endpoint (tag name search) error responses and the error hierarchy."""

from __future__ import annotations

import httpx
import pytest

from aspy21 import AspenBrowseError, AspenClient, AspenError, AspenSqlError

BASE_URL = "https://aspen.local/ProcessData/AtProcessDataREST.dll"
BROWSE_URL = f"{BASE_URL}/Browse"


@pytest.fixture
def client():
    with AspenClient(base_url=BASE_URL, datasource="IP21") as c:
        yield c


def test_error_hierarchy():
    assert issubclass(AspenSqlError, AspenError)
    assert issubclass(AspenBrowseError, AspenError)
    # Existing ValueError handlers keep working
    assert issubclass(AspenError, ValueError)
    assert not issubclass(AspenBrowseError, AspenSqlError)


def test_browse_error_raises(mock_api, client):
    mock_api.get(BROWSE_URL).mock(
        return_value=httpx.Response(
            200, json={"data": {"result": {"er": 1, "ec": 403, "es": "Access denied"}}}
        )
    )

    with pytest.raises(AspenBrowseError, match="Access denied"):
        client.search("TEMP*")


def test_browse_error_caught_as_aspen_error(mock_api, client):
    mock_api.get(BROWSE_URL).mock(
        return_value=httpx.Response(200, json={"data": {"result": {"er": 1, "es": "Failed"}}})
    )

    with pytest.raises(AspenError):
        client.search("TEMP*")


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"unexpected": "structure"}, id="no-data"),
        pytest.param({"data": ["not", "a", "dict"]}, id="data-not-dict"),
        pytest.param({"data": {"tags": "not a list"}}, id="tags-not-list"),
    ],
)
def test_unexpected_structure_raises(mock_api, client, body):
    # Previously returned [], reporting a broken response as "no tags found"
    mock_api.get(BROWSE_URL).mock(return_value=httpx.Response(200, json=body))

    with pytest.raises(AspenBrowseError, match="Unexpected Browse response"):
        client.search("TEMP*")


def test_non_json_body_raises(mock_api, client):
    mock_api.get(BROWSE_URL).mock(return_value=httpx.Response(200, text="<html>Error</html>"))

    with pytest.raises(AspenBrowseError, match="not JSON"):
        client.search("TEMP*")


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"data": {"result": {"er": 0, "ec": 0, "es": ""}}}, id="result-ok"),
        pytest.param({"data": {"tags": []}}, id="empty-tags"),
    ],
)
def test_no_matches_returns_empty_list(mock_api, client, body):
    mock_api.get(BROWSE_URL).mock(return_value=httpx.Response(200, json=body))

    assert client.search("TEMP*") == []


def test_search_with_start_raises_before_reading(mock_api, client):
    """In hybrid mode a Browse error is raised, not turned into an empty read."""
    mock_api.get(BROWSE_URL).mock(
        return_value=httpx.Response(200, json={"data": {"result": {"er": 1, "es": "Failed"}}})
    )

    with pytest.raises(AspenBrowseError):
        client.search("TEMP*", start="2025-01-01 00:00:00", end="2025-01-01 01:00:00")
    assert not any(call.request.url.path.endswith("/SQL") for call in mock_api.calls)
