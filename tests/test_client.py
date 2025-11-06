from datetime import datetime
from typing import cast

import httpx
import pandas as pd
import pytest

from aspy21 import AspenClient, IncludeFields, OutputFormat, ReaderType


def test_read_basic(mock_api):
    # Mock the Aspen API response format
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "samples": [
                            {"t": 1750406400000, "v": 3.0, "s": 8},
                            {"t": 1750410000000, "v": 3.5, "s": 8},
                        ]
                    }
                ]
            },
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    )

    df = c.read(
        ["ATI111"],
        start="2025-06-20 08:00:00",
        end="2025-06-20 09:00:00",
        interval=600,
        read_type=ReaderType.RAW,
        output=OutputFormat.DATAFRAME,
    )
    assert isinstance(df, pd.DataFrame)
    assert "ATI111" in df.columns
    assert df.shape[0] == 2
    c.close()


def test_limit_parameter(mock_api):
    """Test that limit parameter is properly included in XML query."""
    # Mock the API to capture the request
    route = mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll")
    route.mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"samples": [{"t": 1750406400000, "v": 1.0, "s": 8}]}]},
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    )

    # Test with custom limit
    df = c.read(
        ["TAG1"],
        start="2025-06-20 08:00:00",
        end="2025-06-20 09:00:00",
        read_type=ReaderType.RAW,
        limit=250000,
        output=OutputFormat.DATAFRAME,
    )

    # Verify the request was made
    assert route.called
    request = route.calls.last.request
    request_body = request.content.decode("utf-8")

    # Verify limit is in the XML
    assert "<X>250000</X>" in request_body
    assert isinstance(df, pd.DataFrame)
    c.close()


def test_limit_default(mock_api):
    """Test that limit defaults to 100000."""
    route = mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll")
    route.mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"samples": [{"t": 1750406400000, "v": 1.0, "s": 8}]}]},
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    )

    # Test without specifying limit
    df = c.read(
        tags=["TAG1"],
        start="2025-06-20 08:00:00",
        end="2025-06-20 09:00:00",
        read_type=ReaderType.RAW,
        output=OutputFormat.DATAFRAME,
    )

    # Verify the request was made with default limit
    assert route.called
    request = route.calls.last.request
    request_body = request.content.decode("utf-8")

    # Verify default limit (100000) is in the XML
    assert "<X>100000</X>" in request_body
    assert isinstance(df, pd.DataFrame)
    c.close()


def test_limit_enforced_single_tag(mock_api):
    """Ensure limit limits the number of rows returned per tag."""
    route = mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll")
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "samples": [
                            {"t": 1750406400000, "v": 1.0, "s": 8},
                            {"t": 1750408200000, "v": 2.0, "s": 8},
                            {"t": 1750410000000, "v": 3.0, "s": 8},
                        ]
                    }
                ]
            },
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    )

    df = c.read(
        tags=["TAG1"],
        start="2025-06-20 08:00:00",
        end="2025-06-20 09:00:00",
        read_type=ReaderType.RAW,
        limit=2,
        include=IncludeFields.STATUS,
        output=OutputFormat.DATAFRAME,
    )

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df.columns) == ["TAG1", "TAG1_status"]
    c.close()


def test_api_error_response(mock_api):
    """Test handling of API error responses."""
    # Mock API returning an error in the sample
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "samples": [
                            {"er": 1, "es": "Tag not found"},
                        ]
                    }
                ]
            },
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    )

    df = c.read(
        tags=["INVALID_TAG"],
        start="2025-06-20 08:00:00",
        end="2025-06-20 09:00:00",
        read_type=ReaderType.RAW,
        output=OutputFormat.DATAFRAME,
    )

    # Should return empty DataFrame for error responses
    assert isinstance(df, pd.DataFrame)
    assert df.empty
    c.close()


def test_http_error_handling(mock_api):
    """Test handling of HTTP errors."""
    # Mock API returning HTTP 500 error
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll").mock(
        return_value=httpx.Response(
            500,
            text="Internal Server Error",
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    )

    # Should raise RetryError (which wraps HTTPStatusError after retries)
    import pytest
    from tenacity import RetryError

    with pytest.raises(RetryError):
        c.read(
            tags=["TAG1"],
            start="2025-06-20 08:00:00",
            end="2025-06-20 09:00:00",
            read_type=ReaderType.RAW,
        )

    c.close()


def test_aggregated_read_with_interval(mock_api):
    """Test aggregated read with interval parameter."""
    route = mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll")
    route.mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"samples": [{"t": 1750406400000, "v": 5.5, "s": 8}]}]},
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    )

    # Test with AVG reader type and interval
    df = c.read(
        tags=["TAG1"],
        start="2025-06-20 08:00:00",
        end="2025-06-20 09:00:00",
        read_type=ReaderType.AVG,
        interval=600,  # 10 minutes
        output=OutputFormat.DATAFRAME,
    )

    # Verify interval parameters are in the XML
    assert route.called
    request = route.calls.last.request
    request_body = request.content.decode("utf-8")

    assert "<P>600</P>" in request_body  # Period
    assert "<PU>3</PU>" in request_body  # Period unit (seconds)
    assert "<RT>10</RT>" in request_body  # AVG reader type
    assert isinstance(df, pd.DataFrame)
    c.close()


def test_snapshot_read_uses_sql(mock_api, monkeypatch):
    """Test that snapshot reads use SQL endpoint without start/end."""
    route = mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL")
    route.mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "name": "GXV1255.PV",
                    "name->ip_description": "Level Indicator",
                    "name->ip_input_value": 12.5,
                },
                {
                    "name": "GP901.PV",
                    "name->ip_description": "Pump Speed",
                    "name->ip_input_value": 74.0,
                },
            ],
        )
    )

    frozen_time = pd.Timestamp("2025-06-20 09:00:00")
    monkeypatch.setattr(pd.Timestamp, "utcnow", staticmethod(lambda: frozen_time))

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    df = c.read(
        tags=["GXV1255.PV", "GP901.PV"],
        start=None,
        end=None,
        read_type=ReaderType.SNAPSHOT,
        include=IncludeFields.DESCRIPTION,
        output=OutputFormat.DATAFRAME,
    )

    assert route.called
    assert isinstance(df, pd.DataFrame)
    df = cast(pd.DataFrame, df)
    assert list(df.index) == [frozen_time]
    request_body = route.calls.last.request.content.decode("utf-8")
    assert (
        "Select name, name->ip_description, name->ip_input_value, name->ip_input_quality "
        "from all_records where name in ('GXV1255.PV', 'GP901.PV')"
    ) in request_body
    assert df.loc[frozen_time, "GXV1255.PV"] == 12.5
    assert df.loc[frozen_time, "GP901.PV"] == 74.0
    c.close()


def test_read_without_range_defaults_to_snapshot(mock_api, monkeypatch):
    """Missing start/end should automatically fall back to snapshot query."""
    route = mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL")
    route.mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "name": "TAG1",
                    "name->ip_description": "Auto snapshot",
                    "name->ip_input_value": 11.0,
                    "name->ip_input_quality": 192,
                }
            ],
        )
    )

    frozen_time = pd.Timestamp("2025-06-20 10:15:30")
    monkeypatch.setattr(pd.Timestamp, "utcnow", staticmethod(lambda: frozen_time))

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    df = c.read(["TAG1"], output=OutputFormat.DATAFRAME)

    assert route.called
    assert isinstance(df, pd.DataFrame)
    df = cast(pd.DataFrame, df)
    assert list(df.index) == [frozen_time]
    assert df.loc[frozen_time, "TAG1"] == 11.0
    c.close()


def test_read_without_range_snapshot_disallows_status(mock_api, monkeypatch):
    """Snapshot fallback should include quality when include=IncludeFields.STATUS."""
    route = mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL")
    route.mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "name": "TAG1",
                    "name->ip_description": "Auto snapshot",
                    "name->ip_input_value": 22.5,
                    "name->ip_input_quality": 128,
                }
            ],
        )
    )

    frozen_time = pd.Timestamp("2025-06-20 11:00:00")
    monkeypatch.setattr(pd.Timestamp, "utcnow", staticmethod(lambda: frozen_time))

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    df = c.read(["TAG1"], include=IncludeFields.STATUS, output=OutputFormat.DATAFRAME)

    assert route.called
    assert isinstance(df, pd.DataFrame)
    df = cast(pd.DataFrame, df)
    assert df.loc[frozen_time, "TAG1"] == 22.5
    assert df.loc[frozen_time, "TAG1_status"] == 128

    # Verify JSON output also includes status field
    data_json = c.read(["TAG1"], include=IncludeFields.STATUS, output=OutputFormat.JSON)
    assert isinstance(data_json, list)
    assert data_json
    record = data_json[0]
    assert record["tag"] == "TAG1"
    assert record["value"] == 22.5
    assert record["status"] == 128
    assert isinstance(record["timestamp"], str)
    timestamp_str = cast(str, record["timestamp"])
    dt_value = cast(datetime, frozen_time.to_pydatetime())
    assert timestamp_str == dt_value.isoformat()
    c.close()


def test_sql_multi_tag_read_dataframe(mock_api):
    """RAW reads with datasource should use SQL endpoint and merge columns."""
    route = mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL")
    route.mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "ts": "2025-06-20T08:00:00.000000Z",
                    "name": "TAG1",
                    "name->ip_description": "Tag 1 desc",
                    "value": 1.2,
                    "status": 0,
                },
                {
                    "ts": "2025-06-20T08:00:00.000000Z",
                    "name": "TAG2",
                    "name->ip_description": "Tag 2 desc",
                    "value": 5.5,
                    "status": 8,
                },
            ],
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    df = c.read(
        ["TAG1", "TAG2"],
        start="2025-06-20 08:00:00",
        end="2025-06-20 09:00:00",
        read_type=ReaderType.RAW,
        include=IncludeFields.ALL,
        output=OutputFormat.DATAFRAME,
    )

    assert route.called
    assert isinstance(df, pd.DataFrame)
    df = cast(pd.DataFrame, df)
    assert list(df.columns) == [
        "TAG1",
        "TAG1_description",
        "TAG1_status",
        "TAG2",
        "TAG2_description",
        "TAG2_status",
    ]
    ts = pd.Timestamp("2025-06-20T08:00:00Z")
    assert df.loc[ts, "TAG1"] == 1.2
    assert df.loc[ts, "TAG2"] == 5.5
    assert df.loc[ts, "TAG1_status"] == 0
    assert df.loc[ts, "TAG2_status"] == 8
    c.close()


def test_datasource_parameter(mock_api):
    """Test that datasource parameter is included in SQL query for RAW reads."""
    # RAW reads with datasource use SQL endpoint
    route = mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL")
    route.mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "ts": "2025-06-20T08:00:00",
                    "name": "TAG1",
                    "value": 1.0,
                }
            ],
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="MY_DATASOURCE",
    )

    df = c.read(
        tags=["TAG1"],
        start="2025-06-20 08:00:00",
        end="2025-06-20 09:00:00",
        read_type=ReaderType.RAW,
        output=OutputFormat.DATAFRAME,
    )

    # Verify datasource is in the SQL query XML
    assert route.called
    request = route.calls.last.request
    request_body = request.content.decode("utf-8")

    assert 'ds="MY_DATASOURCE"' in request_body
    assert isinstance(df, pd.DataFrame)
    c.close()


def test_empty_response(mock_api):
    """Test handling of empty response from API."""
    # Mock API returning no samples
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"samples": []}]},
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    )

    df = c.read(
        tags=["TAG1"],
        start="2025-06-20 08:00:00",
        end="2025-06-20 09:00:00",
        read_type=ReaderType.RAW,
        output=OutputFormat.DATAFRAME,
    )

    # Should return empty DataFrame
    assert isinstance(df, pd.DataFrame)
    assert df.empty
    c.close()


def test_xml_read_json_with_description(mock_api):
    """Ensure XML endpoint results convert to JSON with description."""
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "samples": [
                            {"t": 1750406400000, "v": 42.0, "s": 4},
                        ],
                        "l": [
                            None,
                            "Flow indicator",
                        ],
                    }
                ]
            },
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    )

    data = c.read(
        ["FI101"],
        start="2025-06-20 08:00:00",
        end="2025-06-20 09:00:00",
        read_type=ReaderType.RAW,
        include=IncludeFields.ALL,
        output=OutputFormat.JSON,
    )

    assert isinstance(data, list)
    assert len(data) == 1
    record = data[0]
    assert record["tag"] == "FI101"
    assert record["description"] == "Flow indicator"
    assert record["value"] == 42.0
    assert record["timestamp"].startswith("2025-06-20T08:00:00")
    c.close()


def test_xml_read_json_without_description_by_default(mock_api):
    """Ensure descriptions are omitted from JSON unless explicitly requested."""
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "samples": [
                            {"t": 1750406400000, "v": 42.0, "s": 4},
                        ],
                        "l": [
                            None,
                            "Flow indicator",
                        ],
                    }
                ]
            },
        )
    )

    with AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    ) as client:
        data = client.read(
            tags=["FI101"],
            start="2025-06-20 08:00:00",
            end="2025-06-20 09:00:00",
            read_type=ReaderType.RAW,
            output=OutputFormat.JSON,
        )

    assert isinstance(data, list)
    assert data
    assert "description" not in data[0]


def test_snapshot_sql_empty_response(mock_api):
    """Snapshot SQL returning no data should yield empty DataFrame."""
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
        return_value=httpx.Response(200, json=[])
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    df = c.read(
        tags=["TAG1"],
        read_type=ReaderType.SNAPSHOT,
        output=OutputFormat.DATAFRAME,
    )

    assert isinstance(df, pd.DataFrame)
    df = cast(pd.DataFrame, df)
    assert df.empty
    c.close()


def test_search_by_tag_pattern(mock_api):
    """Test searching tags by name pattern with wildcards."""
    # Mock Browse endpoint (GET request)
    mock_api.get("https://aspen.local/ProcessData/AtProcessDataREST.dll/Browse").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "tags": [
                        {"t": "TEMP_101", "n": "Reactor temperature"},
                        {"t": "TEMP_102", "n": "Feed temperature"},
                        {"t": "TEMP_103", "n": "Product temperature"},
                    ]
                }
            },
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    # Search with wildcard and get descriptions
    results_raw = c.search("TEMP*", include=IncludeFields.DESCRIPTION)
    # Type narrowing: include=DESCRIPTION guarantees list[dict[str, str]]
    assert isinstance(results_raw, list) and (not results_raw or isinstance(results_raw[0], dict))
    results: list[dict[str, str]] = results_raw  # type: ignore[assignment]

    assert isinstance(results, list)
    assert len(results) == 3
    assert all("name" in tag and "description" in tag for tag in results)
    assert results[0]["name"] == "TEMP_101"
    assert results[0]["description"] == "Reactor temperature"
    c.close()


def test_search_by_description(mock_api):
    """Test searching tags by description using SQL endpoint."""
    # Mock SQL endpoint (POST request with XML) - uses actual Aspen SQL response format
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "g": "aspy21_search",
                        "r": "D",
                        "cols": [
                            {"i": 0, "n": "name"},
                            {"i": 1, "n": "d"},
                            {"i": 2, "n": "name->ip_input_value"},
                        ],
                        "rows": [
                            {
                                "fld": [
                                    {"i": 0, "v": "TEMP_101"},
                                    {"i": 1, "v": "Reactor temperature"},
                                    {"i": 2, "v": "25.5"},
                                ]
                            },
                            {
                                "fld": [
                                    {"i": 0, "v": "PRESS_101"},
                                    {"i": 1, "v": "Reactor pressure"},
                                    {"i": 2, "v": "101.3"},
                                ]
                            },
                        ],
                    }
                ]
            },
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    # Search by description - should use SQL endpoint and return descriptions
    results_raw = c.search(description="reactor", include=IncludeFields.DESCRIPTION)
    # Type narrowing: include=DESCRIPTION guarantees list[dict[str, str]]
    assert isinstance(results_raw, list) and (not results_raw or isinstance(results_raw[0], dict))
    results: list[dict[str, str]] = results_raw  # type: ignore[assignment]

    assert len(results) == 2
    assert results[0]["name"] == "TEMP_101"
    assert results[0]["description"] == "Reactor temperature"
    assert results[1]["name"] == "PRESS_101"
    assert results[1]["description"] == "Reactor pressure"
    c.close()


def test_search_combined_filters(mock_api):
    """Test searching with both tag pattern and description using SQL endpoint."""
    # Mock SQL endpoint (POST request) - SQL WHERE clause filters server-side
    # So the mock should only return records matching BOTH name like 'AI_1%' AND d like '%reactor%'
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "g": "aspy21_search",
                        "r": "D",
                        "cols": [
                            {"i": 0, "n": "name"},
                            {"i": 1, "n": "d"},
                            {"i": 2, "n": "name->ip_input_value"},
                        ],
                        "rows": [
                            {
                                "fld": [
                                    {"i": 0, "v": "AI_101"},
                                    {"i": 1, "v": "Reactor temperature"},
                                    {"i": 2, "v": "25.5"},
                                ]
                            },
                            {
                                "fld": [
                                    {"i": 0, "v": "AI_102"},
                                    {"i": 1, "v": "Reactor pressure"},
                                    {"i": 2, "v": "101.3"},
                                ]
                            },
                            # AI_201 excluded - doesn't match name like 'AI_1%'
                        ],
                    }
                ]
            },
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    # Search with both filters - SQL WHERE clause filters server-side
    results_raw = c.search("AI_1*", description="reactor", include=IncludeFields.DESCRIPTION)
    # Type narrowing: include=DESCRIPTION guarantees list[dict[str, str]]
    assert isinstance(results_raw, list) and (not results_raw or isinstance(results_raw[0], dict))
    results: list[dict[str, str]] = results_raw  # type: ignore[assignment]

    assert len(results) == 2
    assert all("AI_1" in tag["name"] for tag in results)
    assert all("reactor" in tag["description"].lower() for tag in results)
    c.close()


def test_search_case_insensitive(mock_api):
    """Test case-insensitive search by description."""
    # Mock SQL endpoint for description search
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "g": "aspy21_search",
                        "r": "D",
                        "cols": [
                            {"i": 0, "n": "name"},
                            {"i": 1, "n": "d"},
                            {"i": 2, "n": "name->ip_input_value"},
                        ],
                        "rows": [
                            {
                                "fld": [
                                    {"i": 0, "v": "Temperature_101"},
                                    {"i": 1, "v": "Reactor Temp"},
                                    {"i": 2, "v": "25.5"},
                                ]
                            },
                            {
                                "fld": [
                                    {"i": 0, "v": "PRESSURE_101"},
                                    {"i": 1, "v": "Reactor Press"},
                                    {"i": 2, "v": "101.3"},
                                ]
                            },
                        ],
                    }
                ]
            },
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    # Search with lowercase description (should use SQL endpoint)
    results_raw = c.search(description="REACTOR", include=IncludeFields.DESCRIPTION)
    # Type narrowing: include=DESCRIPTION guarantees list[dict[str, str]]
    assert isinstance(results_raw, list) and (not results_raw or isinstance(results_raw[0], dict))
    results: list[dict[str, str]] = results_raw  # type: ignore[assignment]

    assert len(results) == 2  # Case-insensitive match
    c.close()


def test_search_empty_results(mock_api):
    """Test search returning no results."""
    # Mock Browse endpoint returning no tags (GET request)
    mock_api.get("https://aspen.local/ProcessData/AtProcessDataREST.dll/Browse").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"tags": []}},
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    results = c.search(tag="NONEXISTENT*")

    assert isinstance(results, list)
    assert len(results) == 0
    c.close()


def test_search_return_desc_false(mock_api):
    """Test searching with return_desc=False returns just tag names."""
    # Mock Browse endpoint (GET request)
    mock_api.get("https://aspen.local/ProcessData/AtProcessDataREST.dll/Browse").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "tags": [
                        {"t": "TEMP_101", "n": "Reactor temperature"},
                        {"t": "TEMP_102", "n": "Feed temperature"},
                    ]
                }
            },
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    # Search with default include=NONE - should return list of strings
    results_raw = c.search("TEMP*")
    # Type narrowing: include=NONE (default) guarantees list[str]
    assert isinstance(results_raw, list) and (not results_raw or isinstance(results_raw[0], str))
    results: list[str] = results_raw  # type: ignore[assignment]

    assert isinstance(results, list)
    assert len(results) == 2
    assert results[0] == "TEMP_101"
    assert results[1] == "TEMP_102"
    # Verify they are strings, not dicts
    assert isinstance(results[0], str)
    c.close()


def test_search_by_tag_only(mock_api):
    """Test that search() can search by tag without description using Browse endpoint."""
    # Mock Browse endpoint (GET request)
    mock_api.get("https://aspen.local/ProcessData/AtProcessDataREST.dll/Browse").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "tags": [
                        {"t": "AI_101", "n": "Analog input 1"},
                        {"t": "AI_102", "n": "Analog input 2"},
                    ]
                }
            },
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    # Search by tag only (should use Browse endpoint, not SQL)
    results_raw = c.search("AI*", include=IncludeFields.DESCRIPTION)
    # Type narrowing: include=DESCRIPTION guarantees list[dict[str, str]]
    assert isinstance(results_raw, list) and (not results_raw or isinstance(results_raw[0], dict))
    results: list[dict[str, str]] = results_raw  # type: ignore[assignment]

    assert len(results) == 2
    assert results[0]["name"] == "AI_101"
    c.close()


def test_search_requires_datasource():
    """Test that search() requires datasource to be configured."""
    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        # No datasource specified
    )

    # Should raise ValueError
    with pytest.raises(ValueError, match="Datasource is required for search"):
        c.search(tag="TEMP*")

    c.close()


def test_search_hybrid_mode_dataframe(mock_api):
    """Test hybrid search mode: search + read returning DataFrame."""
    # Mock Browse endpoint for search
    mock_api.get("https://aspen.local/ProcessData/AtProcessDataREST.dll/Browse").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "tags": [
                        {"t": "TEMP_101", "n": "Reactor temperature"},
                        {"t": "TEMP_102", "n": "Feed temperature"},
                    ]
                }
            },
        )
    )

    # Mock SQL endpoint for reading data (correct format)
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"ts": "2025-01-01T00:00:00Z", "name": "TEMP_101", "value": 25.5},
                {"ts": "2025-01-01T01:00:00Z", "name": "TEMP_101", "value": 26.0},
                {"ts": "2025-01-01T00:00:00Z", "name": "TEMP_102", "value": 30.0},
                {"ts": "2025-01-01T01:00:00Z", "name": "TEMP_102", "value": 30.5},
            ],
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    # Hybrid mode: search for tags AND read their data
    result = c.search(
        "TEMP*",
        start="2025-01-01 00:00:00",
        end="2025-01-01 01:00:00",
        read_type=ReaderType.RAW,
        output=OutputFormat.DATAFRAME,
    )

    # Should return DataFrame with data for found tags
    assert isinstance(result, pd.DataFrame)
    df = cast(pd.DataFrame, result)
    assert "TEMP_101" in df.columns
    assert "TEMP_102" in df.columns
    assert len(df) == 2
    c.close()


def test_search_hybrid_mode_json(mock_api):
    """Test hybrid search mode: search + read returning JSON."""
    # Mock Browse endpoint for search
    mock_api.get("https://aspen.local/ProcessData/AtProcessDataREST.dll/Browse").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "tags": [
                        {"t": "TEMP_101", "n": "Reactor temperature"},
                    ]
                }
            },
        )
    )

    # Mock SQL endpoint for reading data
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"ts": "2025-01-01T00:00:00Z", "name": "TEMP_101", "value": 25.5},
            ],
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    # Hybrid mode with JSON output (default)
    result = c.search(
        "TEMP*",
        start="2025-01-01 00:00:00",
        end="2025-01-01 01:00:00",
        read_type=ReaderType.RAW,
    )

    # Should return list of dicts
    assert isinstance(result, list)
    assert len(result) == 1
    record = result[0]
    assert isinstance(record, dict)
    assert record["tag"] == "TEMP_101"
    assert record["value"] == 25.5
    assert "timestamp" in record
    c.close()


def test_search_hybrid_mode_with_description_filter(mock_api):
    """Test hybrid mode with description-based search (SQL endpoint)."""
    # Mock SQL endpoint for description search
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").side_effect = [
        # First call: search query
        httpx.Response(
            200,
            json={
                "data": [
                    {
                        "g": "aspy21_search",
                        "r": "D",
                        "cols": [
                            {"i": 0, "n": "name"},
                            {"i": 1, "n": "d"},
                        ],
                        "rows": [
                            {
                                "fld": [
                                    {"i": 0, "v": "REACTOR_TEMP"},
                                    {"i": 1, "v": "Main reactor temperature"},
                                ]
                            }
                        ],
                    }
                ]
            },
        ),
        # Second call: read query
        httpx.Response(
            200,
            json=[
                {"ts": "2025-01-01T00:00:00Z", "name": "REACTOR_TEMP", "value": 125.5},
            ],
        ),
    ]

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    # Hybrid mode with description filter
    result = c.search(
        description="reactor",
        start="2025-01-01 00:00:00",
        end="2025-01-01 01:00:00",
        output=OutputFormat.DATAFRAME,
    )

    assert isinstance(result, pd.DataFrame)
    df = cast(pd.DataFrame, result)
    assert "REACTOR_TEMP" in df.columns
    c.close()


def test_search_hybrid_mode_empty_results(mock_api):
    """Test hybrid mode when search returns no tags."""
    # Mock Browse endpoint returning no tags
    mock_api.get("https://aspen.local/ProcessData/AtProcessDataREST.dll/Browse").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"tags": []}},
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    # Hybrid mode with no matching tags - should return empty DataFrame
    result = c.search(
        "NONEXISTENT*",
        start="2025-01-01 00:00:00",
        output=OutputFormat.DATAFRAME,
    )

    assert isinstance(result, pd.DataFrame)
    assert len(result) == 0

    # Same for JSON output
    result_json = c.search(
        "NONEXISTENT*",
        start="2025-01-01 00:00:00",
        output=OutputFormat.JSON,
    )

    assert isinstance(result_json, list)
    assert len(result_json) == 0
    c.close()


def test_search_hybrid_mode_with_include_all(mock_api):
    """Test hybrid mode with include=ALL (status + description)."""
    # Mock Browse endpoint
    mock_api.get("https://aspen.local/ProcessData/AtProcessDataREST.dll/Browse").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "tags": [
                        {"t": "TAG1", "n": "Tag description"},
                    ]
                }
            },
        )
    )

    # Mock SQL endpoint with status and description
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "ts": "2025-01-01T00:00:00Z",
                    "name": "TAG1",
                    "name->ip_description": "Tag description",
                    "value": 100.0,
                    "status": 8,
                }
            ],
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    # Hybrid mode with include=ALL
    result = c.search(
        "TAG*",
        start="2025-01-01 00:00:00",
        include=IncludeFields.ALL,
        output=OutputFormat.JSON,
    )

    assert isinstance(result, list)
    assert len(result) == 1
    # Should include description and status
    record = result[0]
    assert isinstance(record, dict)
    assert "description" in record
    assert "status" in record
    assert record["tag"] == "TAG1"
    c.close()


def test_search_only_mode_vs_hybrid_mode(mock_api):
    """Test that search behaves differently in search-only vs hybrid mode."""
    # Mock Browse endpoint
    mock_api.get("https://aspen.local/ProcessData/AtProcessDataREST.dll/Browse").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "tags": [
                        {"t": "TAG1", "n": "Description 1"},
                        {"t": "TAG2", "n": "Description 2"},
                    ]
                }
            },
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    # Search-only mode (no start) - returns list of tag names
    result_search_only = c.search("TAG*")

    assert isinstance(result_search_only, list)
    assert len(result_search_only) == 2
    # Default include=NONE returns strings
    assert isinstance(result_search_only[0], str)
    assert result_search_only[0] == "TAG1"

    c.close()


def test_context_manager_basic(mock_api):
    """Test context manager enters and exits properly."""
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"samples": [{"t": 1750406400000, "v": 1.0, "s": 8}]}]},
        )
    )

    # Use context manager
    with AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    ) as client:
        assert client is not None
        df = client.read(
            tags=["TAG1"],
            start="2025-06-20 08:00:00",
            end="2025-06-20 09:00:00",
            read_type=ReaderType.RAW,
            output=OutputFormat.DATAFRAME,
        )
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    # Client should be closed after context manager exits
    # Verify by checking that the underlying httpx client is closed
    assert client._client.is_closed


def test_context_manager_with_exception(mock_api):
    """Test context manager closes even when exception occurs."""
    from tenacity import RetryError

    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll").mock(
        return_value=httpx.Response(500, text="Server Error")
    )

    # Even if an exception occurs, client should be closed
    with (
        pytest.raises(RetryError),
        AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            timeout=2,
            verify_ssl=False,
        ) as client,
    ):
        client.read(
            tags=["TAG1"],
            start="2025-06-20 08:00:00",
            end="2025-06-20 09:00:00",
            read_type=ReaderType.RAW,
        )

    # Client should still be closed
    assert client._client.is_closed


def test_context_manager_returns_self():
    """Test that __enter__ returns self."""
    client = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    )

    # __enter__ should return the client itself
    returned = client.__enter__()
    assert returned is client

    client.close()


def test_read_as_df_basic(mock_api):
    """Test reading data with output=OutputFormat.JSON returns list of dictionaries."""
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "l": ["VAL", "Temperature sensor"],  # Field values including description
                        "samples": [
                            {"t": 1704110400000, "v": 25.5, "s": 8},  # 2024-01-01 12:00:00
                            {"t": 1704114000000, "v": 26.0, "s": 8},  # 2024-01-01 13:00:00
                        ],
                    }
                ]
            },
        )
    )

    with AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    ) as client:
        data = client.read(
            tags=["TAG1"],
            start="2024-01-01 12:00:00",
            end="2024-01-01 13:00:00",
            read_type=ReaderType.RAW,
            include=IncludeFields.DESCRIPTION,
            output=OutputFormat.JSON,
        )

        # Verify it's a list of dicts
        assert isinstance(data, list)
        assert len(data) == 2

        # Verify structure of first record
        assert "timestamp" in data[0]
        assert "tag" in data[0]
        assert "description" in data[0]
        assert "value" in data[0]

        # Verify values
        assert data[0]["tag"] == "TAG1"
        assert data[0]["description"] == "Temperature sensor"
        assert data[0]["value"] == 25.5
        assert isinstance(data[0]["timestamp"], str)

        assert data[1]["value"] == 26.0


def test_read_with_description_dataframe(mock_api):
    """Test reading data with include=IncludeFields.DESCRIPTION still returns DataFrame."""
    route = mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll")
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "l": ["VAL", "Pressure sensor"],  # Field values including description
                        "samples": [
                            {"t": 1704110400000, "v": 101.3, "s": 8},
                        ],
                    }
                ]
            },
        )
    )

    with AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    ) as client:
        df = client.read(
            tags=["PRESS1"],
            start="2024-01-01 12:00:00",
            end="2024-01-01 13:00:00",
            read_type=ReaderType.RAW,
            include=IncludeFields.DESCRIPTION,
            output=OutputFormat.DATAFRAME,
        )

        # Should still return DataFrame when output=OutputFormat.DATAFRAME
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert "PRESS1" in df.columns
        assert "PRESS1_description" in df.columns
        assert df["PRESS1_description"].iloc[0] == "Pressure sensor"
        assert df.attrs["tag_descriptions"]["PRESS1"] == "Pressure sensor"

        # Verify IP_DESCRIPTION field was requested in XML
        request = route.calls.last.request
        request_body = request.content.decode("utf-8")
        assert "<F><![CDATA[IP_DESCRIPTION]]></F>" in request_body


def test_read_as_df_multiple_tags(mock_api):
    """Test as_df with multiple tags."""

    def response_handler(request):
        # Return different data based on which tag is requested
        body = request.content.decode("utf-8")
        if "TAG1" in body:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "l": ["VAL", "Temperature sensor"],
                            "samples": [
                                {"t": 1704110400000, "v": 25.5, "s": 8},
                            ],
                        }
                    ]
                },
            )
        else:  # TAG2
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "l": ["VAL", "Pressure sensor"],
                            "samples": [
                                {"t": 1704110400000, "v": 101.3, "s": 8},
                            ],
                        }
                    ]
                },
            )

    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll").mock(
        side_effect=response_handler
    )

    with AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    ) as client:
        data = client.read(
            tags=["TAG1", "TAG2"],
            start="2024-01-01 12:00:00",
            end="2024-01-01 13:00:00",
            read_type=ReaderType.RAW,
            include=IncludeFields.DESCRIPTION,
            output=OutputFormat.JSON,
        )

        # Should have 2 records (one per tag, same timestamp)
        assert isinstance(data, list)
        assert len(data) == 2

        # Verify both tags are present
        tags = {record["tag"] for record in data}
        assert tags == {"TAG1", "TAG2"}

        # Verify descriptions
        tag1_record = next(r for r in data if r["tag"] == "TAG1")
        tag2_record = next(r for r in data if r["tag"] == "TAG2")

        assert tag1_record["description"] == "Temperature sensor"
        assert tag1_record["value"] == 25.5

        assert tag2_record["description"] == "Pressure sensor"
        assert tag2_record["value"] == 101.3


def test_read_as_df_empty_response(mock_api):
    """Test output=OutputFormat.JSON with empty response returns empty list."""
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"samples": []}]},
        )
    )

    with AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    ) as client:
        data = client.read(
            tags=["TAG1"],
            start="2024-01-01 12:00:00",
            end="2024-01-01 13:00:00",
            read_type=ReaderType.RAW,
            output=OutputFormat.JSON,
        )

        # Should return empty list
        assert isinstance(data, list)
        assert len(data) == 0


def test_read_as_df_without_description(mock_api):
    """Test output=OutputFormat.JSON when description is requested but not available in response."""
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        # No "l" field - description not available
                        "samples": [
                            {"t": 1704110400000, "v": 25.5, "s": 8},
                        ],
                    }
                ]
            },
        )
    )

    with AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
    ) as client:
        data = client.read(
            tags=["TAG1"],
            start="2024-01-01 12:00:00",
            end="2024-01-01 13:00:00",
            read_type=ReaderType.RAW,
            include=IncludeFields.DESCRIPTION,
            output=OutputFormat.JSON,
        )

        # Should still work, but description should be empty string
        assert len(data) == 1
        assert "description" in data[0]
        assert data[0]["description"] == ""
        assert data[0]["value"] == 25.5


def test_aggregates_min_read(mock_api):
    """Test AGG_MIN read type."""
    # Mock SQL endpoint for aggregates query
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"ts": "2025-01-01T00:00:00Z", "name": "TAG1", "min": 10.5},
            ],
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    result = c.read(
        ["TAG1"],
        start="2025-01-01 00:00:00",
        end="2025-01-02 00:00:00",
        read_type=ReaderType.AGG_MIN,
        output=OutputFormat.JSON,
    )

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["tag"] == "TAG1"
    assert result[0]["value"] == 10.5
    c.close()


def test_aggregates_max_read(mock_api):
    """Test AGG_MAX read type."""
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"ts": "2025-01-01T00:00:00Z", "name": "TAG1", "max": 99.5},
            ],
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    result = c.read(
        ["TAG1"],
        start="2025-01-01 00:00:00",
        end="2025-01-02 00:00:00",
        read_type=ReaderType.AGG_MAX,
        output=OutputFormat.DATAFRAME,
    )

    assert isinstance(result, pd.DataFrame)
    df = cast(pd.DataFrame, result)
    assert "TAG1" in df.columns
    assert df.loc[df.index[0], "TAG1"] == 99.5
    c.close()


def test_aggregates_avg_read(mock_api):
    """Test AGG_AVG read type."""
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"ts": "2025-01-01T00:00:00Z", "name": "TAG1", "avg": 55.0},
            ],
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    result = c.read(
        ["TAG1"],
        start="2025-01-01 00:00:00",
        end="2025-01-02 00:00:00",
        read_type=ReaderType.AGG_AVG,
        output=OutputFormat.JSON,
    )

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["value"] == 55.0
    c.close()


def test_aggregates_rng_read(mock_api):
    """Test AGG_RNG (range) read type."""
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"ts": "2025-01-01T00:00:00Z", "name": "TAG1", "rng": 89.0},
            ],
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    result = c.read(
        ["TAG1"],
        start="2025-01-01 00:00:00",
        end="2025-01-02 00:00:00",
        read_type=ReaderType.AGG_RNG,
        output=OutputFormat.JSON,
    )

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["value"] == 89.0
    c.close()


def test_aggregates_multiple_tags(mock_api):
    """Test aggregates with multiple tags."""
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"ts": "2025-01-01T00:00:00Z", "name": "TAG1", "min": 10.5},
                {"ts": "2025-01-01T00:00:00Z", "name": "TAG2", "min": 20.5},
            ],
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    result = c.read(
        ["TAG1", "TAG2"],
        start="2025-01-01 00:00:00",
        end="2025-01-02 00:00:00",
        read_type=ReaderType.AGG_MIN,
        output=OutputFormat.DATAFRAME,
    )

    assert isinstance(result, pd.DataFrame)
    df = cast(pd.DataFrame, result)
    assert "TAG1" in df.columns
    assert "TAG2" in df.columns
    c.close()


def test_aggregates_with_description(mock_api):
    """Test aggregates with description field."""
    mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "ts": "2025-01-01T00:00:00Z",
                    "name": "TAG1",
                    "name->ip_description": "Test Tag Description",
                    "avg": 42.0,
                },
            ],
        )
    )

    c = AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
        timeout=2,
        verify_ssl=False,
        datasource="IP21",
    )

    result = c.read(
        ["TAG1"],
        start="2025-01-01 00:00:00",
        end="2025-01-02 00:00:00",
        read_type=ReaderType.AGG_AVG,
        include=IncludeFields.DESCRIPTION,
        output=OutputFormat.JSON,
    )

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["description"] == "Test Tag Description"
    assert result[0]["value"] == 42.0
    c.close()
