"""Tests for the per-tag row limit of multi-tag history reads.

The mock server behaves like IP.21 does in production: the m="..." row limit applies to
the whole result, and rows come back grouped by tag in the order of the query's tag list.
"""

from __future__ import annotations

import logging
import re

import httpx
import pandas as pd
import pytest

from aspy21 import AspenClient, OutputFormat, ReaderType

BASE_URL = "https://aspen.local/ProcessData/AtProcessDataREST.dll"


def history_server(rows_per_tag: dict[str, int]):
    """Return a side effect answering history queries like IP.21."""

    def respond(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        limit = int(re.search(r' m="(\d+)"', body).group(1))  # type: ignore[union-attr]
        sql = body[body.index("<![CDATA[") :]
        tags = re.findall(r"'([^']+)'", sql.split(" and ts between")[0])
        rows = [
            {"ts": f"2025-01-01T{i // 60:02d}:{i % 60:02d}:00Z", "name": tag, "value": i}
            for tag in tags
            for i in range(rows_per_tag.get(tag, 0))
        ]
        return httpx.Response(200, json=rows[:limit])

    return respond


def read(
    mock_api, rows_per_tag: dict[str, int], tags: list[str], limit: int
) -> tuple[pd.DataFrame, int]:
    """Read RAW data; return the DataFrame and the number of requests sent."""
    route = mock_api.post(f"{BASE_URL}/SQL").mock(side_effect=history_server(rows_per_tag))
    with AspenClient(BASE_URL, datasource="IP21") as client:
        df = client.read(
            tags,
            start="2025-01-01 00:00:00",
            end="2025-01-01 12:00:00",
            read_type=ReaderType.RAW,
            limit=limit,
            output=OutputFormat.DATAFRAME,
        )
    return df, route.call_count


def counts(df: pd.DataFrame, tags: list[str]) -> dict[str, int]:
    return {tag: int(df[tag].count()) if tag in df.columns else 0 for tag in tags}


@pytest.mark.parametrize(
    "tags",
    [["GTIME", "PHASE", "GTI118"], ["GTI118", "PHASE", "GTIME"]],
    ids=["dense-first", "dense-last"],
)
def test_every_tag_gets_its_limit(mock_api, tags):
    """The production case: previously the first tag got 10 rows and the others none."""
    rows = {"GTIME": 120, "PHASE": 60, "GTI118": 38}

    df, calls = read(mock_api, rows, tags, limit=10)

    assert counts(df, tags) == dict.fromkeys(tags, 10)
    assert list(df.columns) == tags
    assert calls == 3  # the batch, then the two tags it cut short


def test_tag_with_fewer_rows_than_limit_is_complete(mock_api):
    df, _ = read(mock_api, {"A": 40, "B": 3}, ["A", "B"], limit=10)

    assert counts(df, ["A", "B"]) == {"A": 10, "B": 3}


def test_one_request_when_limit_not_reached(mock_api):
    df, calls = read(mock_api, {"A": 5, "B": 7}, ["A", "B"], limit=10)

    assert counts(df, ["A", "B"]) == {"A": 5, "B": 7}
    assert calls == 1


def test_one_request_for_one_tag(mock_api):
    df, calls = read(mock_api, {"A": 40}, ["A"], limit=10)

    assert counts(df, ["A"]) == {"A": 10}
    assert calls == 1


def test_warning_when_tag_reaches_limit(mock_api, caplog):
    with caplog.at_level(logging.WARNING):
        read(mock_api, {"A": 40, "B": 3}, ["A", "B"], limit=10)

    assert "A: returned 10 rows, the row limit; values after" in caplog.text
    assert "B: returned" not in caplog.text


def test_no_missing_data_warning_for_tags_read_again(mock_api, caplog):
    """Tags cut short by the batch are not reported as having no data."""
    with caplog.at_level(logging.WARNING):
        read(mock_api, {"A": 40, "B": 30}, ["A", "B"], limit=10)

    assert "No data in SQL response" not in caplog.text


def test_tag_without_data_still_reported(mock_api, caplog):
    with caplog.at_level(logging.WARNING):
        df, _ = read(mock_api, {"A": 40}, ["A", "NONE"], limit=10)

    assert counts(df, ["A", "NONE"]) == {"A": 10, "NONE": 0}
    assert "No data in SQL response" in caplog.text
