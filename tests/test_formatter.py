"""Tests for merging per-tag frames and formatting the result."""

from __future__ import annotations

import httpx
import pandas as pd
import pytest
import respx

from aspy21 import AspenClient, IncludeFields, OutputFormat, ReaderType
from aspy21.readers.formatter import DataFormatter

BASE_URL = "https://aspen.local/ProcessData/AtProcessDataREST.dll"


def frame(tag: str, times: list[str], values: list, status: list | None = None) -> pd.DataFrame:
    data: dict[str, list] = {tag: values}
    if status is not None:
        data[f"{tag}_status"] = status
    return pd.DataFrame(data, index=pd.DatetimeIndex(times, name="time"))


def merge(frames: list[pd.DataFrame], tags: list[str], **kwargs) -> pd.DataFrame:
    result = DataFormatter.format_output(
        frames,
        tags,
        {},
        as_df=True,
        include_status=kwargs.get("include_status", False),
        with_description=False,
    )
    assert isinstance(result, pd.DataFrame)
    return result


def to_json(frames: list[pd.DataFrame], tags: list[str], include_status: bool = False) -> list:
    result = DataFormatter.format_output(
        frames, tags, {}, as_df=False, include_status=include_status, with_description=False
    )
    assert isinstance(result, list)
    return result


class TestMergeGaps:
    def test_tags_with_different_timestamps_align_on_time(self):
        df = merge(
            [
                frame("A", ["2025-01-01 00:00", "2025-01-01 00:02"], [1.0, 3.0]),
                frame("B", ["2025-01-01 00:01", "2025-01-01 00:02"], [20.0, 30.0]),
            ],
            ["A", "B"],
        )

        assert df.index.tolist() == list(
            pd.to_datetime(["2025-01-01 00:00", "2025-01-01 00:01", "2025-01-01 00:02"])
        )
        assert df["A"].tolist()[0::2] == [1.0, 3.0]
        assert pd.isna(df["A"].iloc[1])
        assert pd.isna(df["B"].iloc[0])
        assert df["B"].tolist()[1:] == [20.0, 30.0]
        assert df.index.name == "time"

    def test_status_columns_align_with_values(self):
        df = merge(
            [
                frame("A", ["2025-01-01 00:00"], [1.0], status=[0]),
                frame("B", ["2025-01-01 00:01"], [2.0], status=[1]),
            ],
            ["A", "B"],
            include_status=True,
        )

        assert list(df.columns) == ["A", "A_status", "B", "B_status"]
        assert df.loc["2025-01-01 00:01", "B_status"] == 1
        assert pd.isna(df.loc["2025-01-01 00:01", "A_status"])

    def test_result_sorted_by_time(self):
        df = merge(
            [
                frame("A", ["2025-01-01 00:02", "2025-01-01 00:00"], [3.0, 1.0]),
                frame("B", ["2025-01-01 00:01"], [2.0]),
            ],
            ["A", "B"],
        )

        assert df.index.is_monotonic_increasing
        assert df["A"].dropna().tolist() == [1.0, 3.0]

    def test_json_has_one_record_per_value(self):
        records = to_json(
            [
                frame("A", ["2025-01-01 00:00", "2025-01-01 00:02"], [1.5, 3.5]),
                frame("B", ["2025-01-01 00:01"], [20.5]),
            ],
            ["A", "B"],
        )

        assert [(r["timestamp"], r["tag"], r["value"]) for r in records] == [
            ("2025-01-01T00:00:00", "A", 1.5),
            ("2025-01-01T00:01:00", "B", 20.5),
            ("2025-01-01T00:02:00", "A", 3.5),
        ]


class TestMergeDuplicateTimestamps:
    """Raw history can hold several values of one tag at the same timestamp."""

    def test_duplicate_in_one_tag_with_other_tag_elsewhere(self):
        # Previously raised InvalidIndexError
        df = merge(
            [
                frame("A", ["2025-01-01 00:00", "2025-01-01 00:00"], [1, 2]),
                frame("B", ["2025-01-01 00:01"], [20]),
            ],
            ["A", "B"],
        )

        assert len(df) == 3
        assert df["A"].dropna().tolist() == [1, 2]
        assert df["B"].dropna().tolist() == [20]

    def test_other_tag_at_same_timestamp_not_repeated(self):
        # Previously B's value was copied onto both of A's rows
        df = merge(
            [
                frame("A", ["2025-01-01 00:00", "2025-01-01 00:00"], [1, 2]),
                frame("B", ["2025-01-01 00:00"], [20]),
            ],
            ["A", "B"],
        )

        assert df["A"].tolist() == [1, 2]
        assert df["B"].iloc[0] == 20
        assert pd.isna(df["B"].iloc[1])

    def test_duplicates_in_both_tags_pair_in_order(self):
        df = merge(
            [
                frame("A", ["2025-01-01 00:00", "2025-01-01 00:00"], [1, 2]),
                frame("B", ["2025-01-01 00:00", "2025-01-01 00:00"], [20, 30]),
            ],
            ["A", "B"],
        )

        assert df["A"].tolist() == [1, 2]
        assert df["B"].tolist() == [20, 30]

    def test_order_within_timestamp_kept(self):
        df = merge(
            [frame("A", ["2025-01-01 00:00"] * 3 + ["2025-01-01 00:01"], [5, 3, 4, 1])],
            ["A"],
        )

        assert df["A"].tolist() == [5, 3, 4, 1]

    def test_json_keeps_every_value(self):
        records = to_json(
            [
                frame("A", ["2025-01-01 00:00", "2025-01-01 00:00"], [1, 2]),
                frame("B", ["2025-01-01 00:00"], [20]),
            ],
            ["A", "B"],
        )

        assert [(r["tag"], r["value"]) for r in records] == [("A", 1), ("B", 20), ("A", 2)]


class TestJsonValues:
    def test_integer_values_returned(self):
        # Previously numpy.int64 values failed an isinstance check and were dropped
        records = to_json([frame("A", ["2025-01-01 00:00", "2025-01-01 00:01"], [1, 2])], ["A"])

        assert [r["value"] for r in records] == [1, 2]

    @pytest.mark.parametrize(
        ("values", "expected_type"),
        [([1, 2], int), ([1.5, 2.5], float), (["ON", "OFF"], str), ([True, False], bool)],
    )
    def test_values_are_python_types(self, values, expected_type):
        records = to_json([frame("A", ["2025-01-01 00:00", "2025-01-01 00:01"], values)], ["A"])

        assert [r["value"] for r in records] == values
        assert all(type(r["value"]) is expected_type for r in records)

    def test_integer_tag_next_to_float_tag_stays_integer(self):
        records = to_json(
            [frame("A", ["2025-01-01 00:00"], [1]), frame("B", ["2025-01-01 00:00"], [2.5])],
            ["A", "B"],
        )

        assert [(r["value"], type(r["value"])) for r in records] == [(1, int), (2.5, float)]

    def test_integer_status_returned(self):
        records = to_json(
            [frame("A", ["2025-01-01 00:00"], [1.5], status=[0])],
            ["A"],
            include_status=True,
        )

        assert records[0]["status"] == 0
        assert type(records[0]["status"]) is int

    def test_missing_values_skipped(self):
        records = to_json([frame("A", ["2025-01-01 00:00", "2025-01-01 00:01"], [pd.NA, 2])], ["A"])

        assert [r["value"] for r in records] == [2]


@respx.mock
@pytest.mark.parametrize("output", [OutputFormat.JSON, OutputFormat.DATAFRAME])
def test_read_with_duplicates_and_integers(output):
    """End to end: a RAW read with integer values and a repeated timestamp."""
    respx.post(f"{BASE_URL}/SQL").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"name": "A", "ts": "2025-01-01T00:00:00Z", "value": 1, "status": 0},
                {"name": "A", "ts": "2025-01-01T00:00:00Z", "value": 2, "status": 0},
                {"name": "B", "ts": "2025-01-01T00:01:00Z", "value": 20, "status": 0},
            ],
        )
    )
    with AspenClient(BASE_URL, datasource="IP21") as client:
        result = client.read(
            ["A", "B"],
            start="2025-01-01 00:00:00",
            end="2025-01-01 01:00:00",
            read_type=ReaderType.RAW,
            include=IncludeFields.STATUS,
            output=output,
        )

    if output == OutputFormat.JSON:
        assert isinstance(result, list)
        assert [(r["tag"], r["value"], r["status"]) for r in result] == [
            ("A", 1, 0),
            ("A", 2, 0),
            ("B", 20, 0),
        ]
    else:
        assert isinstance(result, pd.DataFrame)
        assert result["A"].dropna().tolist() == [1, 2]
        assert result["B"].dropna().tolist() == [20]


class TestJsonFromFrames:
    """JSON records are built from the readers' frames, not the merged DataFrame."""

    def test_integer_tags_with_gaps_stay_integer(self):
        # Previously 1.0 and 0.0: in the merged DataFrame both columns have gaps
        records = to_json(
            [
                frame("A", ["2025-01-01 00:00"], [1], status=[0]),
                frame("B", ["2025-01-01 00:01"], [2], status=[0]),
            ],
            ["A", "B"],
            include_status=True,
        )

        assert [(r["value"], r["status"]) for r in records] == [(1, 0), (2, 0)]
        assert all(type(r["value"]) is int and type(r["status"]) is int for r in records)

    def test_json_matches_dataframe_values_and_order(self):
        frames = [
            frame(
                "A",
                ["2025-01-01 00:02", "2025-01-01 00:00", "2025-01-01 00:00"],
                [3, 1, 2],
                status=[0, 1, 0],
            ),
            frame("B", ["2025-01-01 00:00", "2025-01-01 00:01"], [10.5, 20.5], status=[0, 0]),
        ]
        tags = ["A", "B"]

        df = merge(frames, tags)
        expected = [
            (ts.isoformat(), tag, df[tag].iloc[i])
            for i, ts in enumerate(df.index)
            for tag in tags
            if pd.notna(df[tag].iloc[i])
        ]
        records = to_json(frames, tags)

        assert [(r["timestamp"], r["tag"], r["value"]) for r in records] == expected

    def test_tag_order_within_timestamp_follows_request(self):
        frames = [
            frame("A", ["2025-01-01 00:00"], [1]),
            frame("B", ["2025-01-01 00:00"], [2]),
        ]

        assert [r["tag"] for r in to_json(frames, ["B", "A"])] == ["B", "A"]
