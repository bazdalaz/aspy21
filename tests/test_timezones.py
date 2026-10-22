"""Tests for server-local time handling.

An IP.21 server in a UTC+3 zone showed that:
- query timestamps are interpreted as server local time, and
- returned timestamps are server local wall-clock times labelled "Z", e.g. a history
  window requested from local 06:17:09 came back as "2026-10-22T06:17:09.000000Z",
  and getdbtime returned "08:17:10Z" when UTC was 05:17.
"""

from datetime import datetime, timezone
from typing import Any, cast

import httpx
import pandas as pd
import pytest

from aspy21 import AspenClient, OutputFormat, ReaderType
from aspy21.utils import localize_server_index, to_server_time

BASE_URL = "https://aspen.local/ProcessData/AtProcessDataREST.dll"
SQL_URL = f"{BASE_URL}/SQL"

# Shape of a real history response (response="Record")
HISTORY_RESPONSE = [
    {"ts": "2026-10-22T06:17:09.000000Z", "name": "T1", "value": 6.17},
    {"ts": "2026-10-22T06:22:09.000000Z", "name": "T1", "value": 6.22},
]
RANGE: dict[str, Any] = {"start": "2026-10-22 06:17:09", "end": "2026-10-22 06:27:09"}


def sent_sql(route) -> str:
    return route.calls.last.request.content.decode()


def test_history_timestamps_are_server_local_by_default(mock_api):
    mock_api.post(SQL_URL).mock(return_value=httpx.Response(200, json=HISTORY_RESPONSE))

    with AspenClient(base_url=BASE_URL, datasource="IP21") as c:
        result = c.read(["T1"], **RANGE, read_type=ReaderType.RAW)

    assert isinstance(result, list)
    assert [r["timestamp"] for r in result] == ["2026-10-22T06:17:09", "2026-10-22T06:22:09"]


def test_history_timestamps_with_server_timezone(mock_api):
    mock_api.post(SQL_URL).mock(return_value=httpx.Response(200, json=HISTORY_RESPONSE))

    with AspenClient(base_url=BASE_URL, datasource="IP21", server_timezone="Europe/Athens") as c:
        result = c.read(["T1"], **RANGE, read_type=ReaderType.RAW)
        df = c.read(["T1"], **RANGE, read_type=ReaderType.RAW, output=OutputFormat.DATAFRAME)

    assert isinstance(result, list)
    assert result[0]["timestamp"] == "2026-10-22T06:17:09+03:00"
    assert isinstance(df, pd.DataFrame)
    assert df.index[0] == pd.Timestamp("2026-10-22T03:17:09Z")


def test_naive_input_is_sent_unchanged(mock_api):
    route = mock_api.post(SQL_URL).mock(return_value=httpx.Response(200, json=[]))

    with AspenClient(base_url=BASE_URL, datasource="IP21", server_timezone="Europe/Athens") as c:
        c.read(["T1"], **RANGE, read_type=ReaderType.RAW)

    assert "'22-Oct-26 06:17:09' and '22-Oct-26 06:27:09'" in sent_sql(route)


@pytest.mark.parametrize("read_type", [ReaderType.RAW, ReaderType.AVG])
def test_aware_input_is_converted_to_server_timezone(mock_api, read_type):
    route = mock_api.post(SQL_URL).mock(return_value=httpx.Response(200, json=[]))

    with AspenClient(base_url=BASE_URL, datasource="IP21", server_timezone="Europe/Athens") as c:
        c.read(
            ["T1"],
            start="2026-10-22T03:17:09Z",
            end="2026-10-22T03:27:09+00:00",
            read_type=read_type,
        )

    sql = sent_sql(route)
    assert "22-Oct-26 06:17:09" in sql
    assert "22-Oct-26 06:27:09" in sql


def test_aware_input_without_server_timezone_uses_local_zone():
    utc = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    expected = utc.astimezone().replace(tzinfo=None)

    assert to_server_time("2026-01-15T12:00:00Z", None) == pd.Timestamp(expected)


def test_snapshot_time_default_is_naive_local(mock_api):
    mock_api.post(SQL_URL).mock(
        return_value=httpx.Response(200, json=[{"name": "T1", "name->ip_input_value": 8.16}])
    )

    with AspenClient(base_url=BASE_URL, datasource="IP21") as c:
        df = c.read(["T1"], output=OutputFormat.DATAFRAME)

    assert isinstance(df, pd.DataFrame)
    ts = cast(pd.Timestamp, df.index[0])
    assert ts.tzinfo is None
    assert abs(ts - pd.Timestamp.now()) < pd.Timedelta(minutes=1)


def test_snapshot_time_with_server_timezone(mock_api):
    mock_api.post(SQL_URL).mock(
        return_value=httpx.Response(200, json=[{"name": "T1", "name->ip_input_value": 8.16}])
    )

    with AspenClient(base_url=BASE_URL, datasource="IP21", server_timezone="Europe/Athens") as c:
        df = c.read(["T1"], output=OutputFormat.DATAFRAME)

    assert isinstance(df, pd.DataFrame)
    ts = cast(pd.Timestamp, df.index[0])
    assert str(ts.tzinfo) == "Europe/Athens"
    assert abs(ts - pd.Timestamp.now(tz="UTC")) < pd.Timedelta(minutes=1)


def test_invalid_server_timezone_raises():
    with pytest.raises(ValueError, match="server_timezone"):
        AspenClient(base_url=BASE_URL, server_timezone="Not/AZone")


def test_aware_end_in_past_is_cached(mock_api):
    route = mock_api.post(SQL_URL).mock(return_value=httpx.Response(200, json=HISTORY_RESPONSE))

    with AspenClient(base_url=BASE_URL, datasource="IP21", cache=True) as c:
        for _ in range(2):
            c.read(
                ["T1"],
                start="2020-01-01T00:00:00Z",
                end="2020-01-01T01:00:00Z",
                read_type=ReaderType.RAW,
            )

    assert route.call_count == 1


def test_repeated_hour_when_clocks_go_back_is_inferred():
    # Europe/Berlin: 02:00-03:00 occurs twice on 2025-10-26
    times = ["01:30", "02:30", "02:30", "03:30"]
    df = pd.DataFrame(
        {"T1": [1, 2, 3, 4]},
        index=pd.DatetimeIndex([f"2025-10-26T{t}:00Z" for t in times]),
    )

    result = localize_server_index(df, "Europe/Berlin")

    assert [ts.utcoffset().total_seconds() / 3600 for ts in result.index] == [2, 2, 1, 1]


def test_single_ambiguous_time_does_not_raise():
    df = pd.DataFrame({"T1": [1]}, index=pd.DatetimeIndex(["2025-10-26T02:30:00"]))

    result = localize_server_index(df, "Europe/Berlin")

    assert result.index[0] == pd.Timestamp("2025-10-26T02:30:00+01:00")
