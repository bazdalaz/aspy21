"""Tests for SQL endpoint error responses and empty results.

IP.21 reports SQL errors with HTTP 200. These must raise instead of being
treated as "no data" (and then cached as an empty result).
"""

from typing import Any

import httpx
import pandas as pd
import pytest

from aspy21 import AspenClient, AspenSqlError, OutputFormat, ReaderType

BASE_URL = "https://aspen.local/ProcessData/AtProcessDataREST.dll"
SQL_URL = f"{BASE_URL}/SQL"

# Exact error payload returned by a production IP.21 server for invalid SQL
ATPD_ERROR = [
    {
        "AtPD_ErrorCode": -2147467259,
        "AtPD_ErrorString": 'Expecting operator, found character constant " or name = "',
        "AtPD_ADO_ErrorCode": -2147467259,
        "AtPD_ADO_ErrorString": 'Expecting operator, found character constant " or name = "',
    }
]

# Exact error payload returned by a production IP.21 server for invalid SQL (response="Original")
ORIGINAL_ERROR = {
    "data": [
        {
            "g": "aspy21_search",
            "r": "E",
            "ec": -2147467259,
            "es": "Closing quote missing for: ",
            "aec": -2147467259,
            "aes": "Closing quote missing for: ",
            "s": "Select name from all_records where name = 'O'Brien'",
        }
    ]
}

HISTORY: dict[str, Any] = {"start": "2025-01-01 00:00:00", "end": "2025-01-01 01:00:00"}


@pytest.fixture
def client():
    with AspenClient(base_url=BASE_URL, datasource="IP21") as c:
        yield c


def test_sql_error_is_value_error():
    assert issubclass(AspenSqlError, ValueError)


@pytest.mark.parametrize(
    "read_kwargs",
    [
        pytest.param({**HISTORY, "read_type": ReaderType.RAW}, id="history"),
        pytest.param({}, id="snapshot"),
        pytest.param({**HISTORY, "read_type": ReaderType.AVG}, id="aggregates"),
    ],
)
def test_read_raises_on_atpd_error(mock_api, client, read_kwargs):
    mock_api.post(SQL_URL).mock(return_value=httpx.Response(200, json=ATPD_ERROR))

    with pytest.raises(AspenSqlError, match="Expecting operator"):
        client.read(["T1"], **read_kwargs)


def test_aggregates_raises_on_result_error(mock_api, client):
    mock_api.post(SQL_URL).mock(
        return_value=httpx.Response(
            200, json={"data": [{"result": {"er": 1, "es": "Invalid aggregate period"}}]}
        )
    )

    with pytest.raises(AspenSqlError, match="Invalid aggregate period"):
        client.read(["T1"], **HISTORY, read_type=ReaderType.AVG)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(ATPD_ERROR, id="atpd-list"),
        pytest.param(ATPD_ERROR[0], id="atpd-dict"),
        pytest.param({"data": [ATPD_ERROR[0]]}, id="atpd-in-data"),
    ],
)
def test_search_raises_on_atpd_error(mock_api, client, payload):
    mock_api.post(SQL_URL).mock(return_value=httpx.Response(200, json=payload))

    with pytest.raises(AspenSqlError, match="Expecting operator"):
        client.search(description="temp")


def test_search_raises_on_original_format_error(mock_api, client):
    mock_api.post(SQL_URL).mock(return_value=httpx.Response(200, json=ORIGINAL_ERROR))

    with pytest.raises(AspenSqlError, match="Closing quote missing"):
        client.search(description="temp")


def test_snapshot_empty_body_returns_no_data(mock_api, client):
    """IP.21 returns 200 with an empty body for a snapshot of an unknown tag."""
    mock_api.post(SQL_URL).mock(
        return_value=httpx.Response(200, content=b"", headers={"content-length": "0"})
    )

    assert client.read(["NO_SUCH_TAG"]) == []
    df = client.read(["NO_SUCH_TAG"], output=OutputFormat.DATAFRAME)
    assert isinstance(df, pd.DataFrame) and df.empty


def test_malformed_history_record_raises(mock_api, client):
    """Unexpected record shapes must not be silently turned into "no data"."""
    mock_api.post(SQL_URL).mock(
        return_value=httpx.Response(200, json=[{"name": "T1", "value": 1.0}])
    )

    with pytest.raises(KeyError):
        client.read(["T1"], **HISTORY, read_type=ReaderType.RAW)


def test_error_is_not_cached(mock_api):
    route = mock_api.post(SQL_URL).mock(
        side_effect=[
            httpx.Response(200, json=ATPD_ERROR),
            httpx.Response(200, json=[{"ts": "2025-01-01T00:00:00Z", "name": "T1", "value": 1.0}]),
        ]
    )

    with AspenClient(base_url=BASE_URL, datasource="IP21", cache=True) as c:
        with pytest.raises(AspenSqlError):
            c.read(["T1"], **HISTORY, read_type=ReaderType.RAW)
        result = c.read(["T1"], **HISTORY, read_type=ReaderType.RAW)

    assert route.call_count == 2
    assert result == [{"timestamp": "2025-01-01T00:00:00", "tag": "T1", "value": 1.0}]


def test_empty_result_is_not_cached(mock_api):
    """An empty historical read may be a transient condition; don't pin it for 24h."""
    route = mock_api.post(SQL_URL).mock(
        side_effect=[
            httpx.Response(200, json=[]),
            httpx.Response(200, json=[{"ts": "2025-01-01T00:00:00Z", "name": "T1", "value": 1.0}]),
        ]
    )

    with AspenClient(base_url=BASE_URL, datasource="IP21", cache=True) as c:
        assert c.read(["T1"], **HISTORY, read_type=ReaderType.RAW) == []
        result = c.read(["T1"], **HISTORY, read_type=ReaderType.RAW)

    assert route.call_count == 2
    assert len(result) == 1
