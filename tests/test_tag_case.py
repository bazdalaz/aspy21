"""Tests for tag names whose case differs between the request and the response.

IP.21 tag names are case-insensitive: a query for 'tag1.pv' returns rows named 'TAG1.PV'.
"""

from __future__ import annotations

import logging

import httpx
import pandas as pd

from aspy21 import AspenClient, IncludeFields, OutputFormat, ReaderType
from aspy21.readers.response_parser import (
    SqlAggregatesResponseParser,
    SqlHistoryResponseParser,
    SqlSnapshotResponseParser,
)

BASE_URL = "https://aspen.local/ProcessData/AtProcessDataREST.dll"


def history_record(ts: str, value: object) -> dict:
    return {"ts": ts, "name": "TAG1.PV", "value": value, "name->ip_description": "Time"}


def test_history_matches_tag_case_insensitively(caplog):
    response = [
        history_record("2025-01-01T00:00:00Z", 1),
        history_record("2025-01-01T00:01:00Z", 2),
    ]

    with caplog.at_level(logging.WARNING):
        frames, descriptions = SqlHistoryResponseParser().parse(
            response, ["tag1.pv"], include_status=False, max_rows=0
        )

    assert len(frames) == 1
    # Columns and descriptions use the name as requested
    assert list(frames[0].columns) == ["tag1.pv"]
    assert frames[0]["tag1.pv"].tolist() == [1, 2]
    assert descriptions == {"tag1.pv": "Time"}
    assert "No data" not in caplog.text


def test_history_same_tag_in_two_spellings():
    response = [history_record("2025-01-01T00:00:00Z", 1)]

    frames, _ = SqlHistoryResponseParser().parse(
        response, ["tag1.pv", "TAG1.PV"], include_status=False, max_rows=0
    )

    assert [list(frame.columns) for frame in frames] == [["tag1.pv"], ["TAG1.PV"]]


def test_snapshot_matches_tag_case_insensitively():
    response = [
        {
            "name": "TAG2.PV",
            "name->ip_input_value": 3.5,
            "name->ip_description": "Temperature",
        }
    ]

    df, descriptions = SqlSnapshotResponseParser().parse(
        response,
        ["tag2.pv"],
        include_status=False,
        snapshot_time=pd.Timestamp("2025-01-01 00:00:00"),  # type: ignore[arg-type]
    )

    assert df["tag2.pv"].tolist() == [3.5]
    assert descriptions == {"tag2.pv": "Temperature"}


def test_aggregates_match_tag_case_insensitively():
    response = [
        {"name": "TAG2.PV", "ts": "2025-01-01T01:00:00Z", "avg": 4.5, "ip_description": "T"}
    ]

    frames, descriptions = SqlAggregatesResponseParser().parse(
        response, ["tag2.pv"], value_column="avg", max_rows=0
    )

    assert len(frames) == 1
    assert frames[0]["tag2.pv"].tolist() == [4.5]
    assert descriptions == {"tag2.pv": "T"}


def test_read_with_lowercase_tag(mock_api):
    """The production case: every lowercase tag was reported as having no data."""
    mock_api.post(f"{BASE_URL}/SQL").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"ts": "2025-01-01T00:00:00Z", "name": "TAG1.PV", "value": 1.5},
                {"ts": "2025-01-01T00:00:00Z", "name": "TAG3.PV", "value": 2.5},
            ],
        )
    )

    with AspenClient(BASE_URL, datasource="IP21") as client:
        data = client.read(
            ["tag1.pv", "tag3.pv"],
            start="2025-01-01 00:00:00",
            end="2025-01-01 01:00:00",
            read_type=ReaderType.RAW,
            include=IncludeFields.NONE,
            output=OutputFormat.JSON,
        )

    assert [(r["tag"], r["value"]) for r in data] == [("tag1.pv", 1.5), ("tag3.pv", 2.5)]
