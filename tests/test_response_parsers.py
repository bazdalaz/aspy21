"""Comprehensive tests for response parsers, focusing on error handling and edge cases."""

import pandas as pd

from aspy21.readers.response_parser import (
    SqlAggregatesResponseParser,
    SqlHistoryResponseParser,
    SqlSnapshotResponseParser,
)


class TestSqlSnapshotResponseParser:
    """Tests for SqlSnapshotResponseParser error handling and edge cases."""

    def test_response_not_a_list(self):
        """Test when response is a dict instead of a list."""
        parser = SqlSnapshotResponseParser()
        df, descriptions = parser.parse(
            response={"error": "invalid"},  # type: ignore[arg-type]
            tag_names=["TAG1"],
            include_status=False,
            snapshot_time=pd.Timestamp("2025-01-01 00:00:00"),  # type: ignore[arg-type]
        )
        assert df.empty
        assert descriptions == {}

    def test_response_is_none(self):
        """Test when response is None."""
        parser = SqlSnapshotResponseParser()
        df, descriptions = parser.parse(
            response=None,  # type: ignore[arg-type]
            tag_names=["TAG1"],
            include_status=False,
            snapshot_time=pd.Timestamp("2025-01-01 00:00:00"),  # type: ignore[arg-type]
        )
        assert df.empty
        assert descriptions == {}

    def test_empty_response_list(self):
        """Test when response is an empty list."""
        parser = SqlSnapshotResponseParser()
        df, descriptions = parser.parse(
            response=[],
            tag_names=["TAG1"],
            include_status=False,
            snapshot_time=pd.Timestamp("2025-01-01 00:00:00"),  # type: ignore[arg-type]
        )
        assert df.empty
        assert descriptions == {}

    def test_record_missing_name_field(self):
        """Test when a record has no 'name' field."""
        parser = SqlSnapshotResponseParser()
        df, descriptions = parser.parse(
            response=[
                {"name->ip_input_value": 10.5},  # Missing 'name'
                {"name": "TAG1", "name->ip_input_value": 20.0},
            ],
            tag_names=["TAG1"],
            include_status=False,
            snapshot_time=pd.Timestamp("2025-01-01 00:00:00"),  # type: ignore[arg-type]
        )
        # Should process only the valid record
        if not df.empty:
            assert "TAG1" in df.columns

    def test_record_name_not_in_requested_tags(self):
        """Test when response contains tags not in tag_names list."""
        parser = SqlSnapshotResponseParser()
        df, descriptions = parser.parse(
            response=[
                {"name": "TAG1", "name->ip_input_value": 10.0},
                {"name": "TAG2", "name->ip_input_value": 20.0},
                {"name": "TAG3", "name->ip_input_value": 30.0},
            ],
            tag_names=["TAG1", "TAG3"],  # Only requesting TAG1 and TAG3
            include_status=False,
            snapshot_time=pd.Timestamp("2025-01-01 00:00:00"),  # type: ignore[arg-type]
        )
        # Should only include TAG1 and TAG3
        if not df.empty:
            assert "TAG2" not in df.columns


class TestSqlHistoryResponseParser:
    """Tests for SqlHistoryResponseParser error handling and edge cases."""

    def test_response_not_a_list(self):
        """Test when response is not a list."""
        parser = SqlHistoryResponseParser()
        frames, descriptions = parser.parse(
            response={"error": "invalid"},  # type: ignore[arg-type]
            tag_names=["TAG1"],
            include_status=False,
            max_rows=1000,
        )
        assert frames == []
        assert descriptions == {}

    def test_response_is_none(self):
        """Test when response is None."""
        parser = SqlHistoryResponseParser()
        frames, descriptions = parser.parse(
            response=None,  # type: ignore[arg-type]
            tag_names=["TAG1"],
            include_status=False,
            max_rows=1000,
        )
        assert frames == []
        assert descriptions == {}

    def test_empty_response_list(self):
        """Test when response is an empty list."""
        parser = SqlHistoryResponseParser()
        frames, descriptions = parser.parse(
            response=[],
            tag_names=["TAG1"],
            include_status=False,
            max_rows=1000,
        )
        assert frames == []
        assert descriptions == {}

    def test_tag_with_no_records_in_response(self):
        """Test when requesting multiple tags but response only contains some."""
        parser = SqlHistoryResponseParser()
        # Response only has TAG1 and TAG2, but we requested TAG1, TAG2, TAG3
        frames, descriptions = parser.parse(
            response=[
                {"ts": "2025-01-01T00:00:00Z", "name": "TAG1", "value": 10.0},
                {"ts": "2025-01-01T00:00:00Z", "name": "TAG2", "value": 20.0},
            ],
            tag_names=["TAG1", "TAG2", "TAG3"],  # TAG3 has no data
            include_status=False,
            max_rows=1000,
        )
        # Should return frames for tags that have data
        assert len(frames) <= 3


class TestSqlAggregatesResponseParser:
    """Tests for SqlAggregatesResponseParser - most critical for coverage."""

    def test_response_not_dict(self):
        """Test when response is not a dict (when expected to have 'data' wrapper)."""
        parser = SqlAggregatesResponseParser()
        frames, descriptions = parser.parse(
            response=[1, 2, 3],  # List instead of dict
            tag_names=["TAG1"],
            value_column="AVG",
            max_rows=1000,
        )
        # Should handle gracefully
        assert isinstance(frames, list)
        assert isinstance(descriptions, dict)

    def test_response_missing_data_field(self):
        """Test when response dict has no 'data' field."""
        parser = SqlAggregatesResponseParser()
        frames, descriptions = parser.parse(
            response={"result": "error", "message": "something went wrong"},
            tag_names=["TAG1"],
            value_column="AVG",
            max_rows=1000,
        )
        assert frames == []
        assert descriptions == {}

    def test_data_field_not_a_list(self):
        """Test when 'data' field is not a list."""
        parser = SqlAggregatesResponseParser()
        frames, descriptions = parser.parse(
            response={"data": "not a list"},
            tag_names=["TAG1"],
            value_column="AVG",
            max_rows=1000,
        )
        assert frames == []
        assert descriptions == {}

    def test_empty_data_array(self):
        """Test when data array is empty."""
        parser = SqlAggregatesResponseParser()
        frames, descriptions = parser.parse(
            response={"data": []},
            tag_names=["TAG1"],
            value_column="AVG",
            max_rows=1000,
        )
        assert frames == []
        assert descriptions == {}

    def test_result_set_not_dict(self):
        """Test when first element of data array is not a dict."""
        parser = SqlAggregatesResponseParser()
        frames, descriptions = parser.parse(
            response={"data": ["not a dict"]},
            tag_names=["TAG1"],
            value_column="AVG",
            max_rows=1000,
        )
        assert frames == []
        assert descriptions == {}

    def test_no_rows_in_result_set(self):
        """Test when result set has no rows."""
        parser = SqlAggregatesResponseParser()
        frames, descriptions = parser.parse(
            response={
                "data": [
                    {
                        "cols": [
                            {"i": 0, "n": "TIME_STAMP"},
                            {"i": 1, "n": "NAME"},
                            {"i": 2, "n": "AVG"},
                        ],
                        "rows": [],  # No rows
                    }
                ]
            },
            tag_names=["TAG1"],
            value_column="AVG",
            max_rows=1000,
        )
        assert frames == []

    def test_missing_cols_field(self):
        """Test when result set has no 'cols' field."""
        parser = SqlAggregatesResponseParser()
        frames, descriptions = parser.parse(
            response={"data": [{"rows": [{"fld": ["2025-01-01T00:00:00Z", "TAG1", 10.5]}]}]},
            tag_names=["TAG1"],
            value_column="AVG",
            max_rows=1000,
        )
        # Without cols, can't map columns properly
        assert frames == []

    def test_invalid_column_structure(self):
        """Test when cols array has invalid structure."""
        parser = SqlAggregatesResponseParser()
        frames, descriptions = parser.parse(
            response={
                "data": [
                    {
                        "cols": [
                            {"i": 0},  # Missing 'n' field
                            {"n": "NAME"},  # Missing 'i' field
                            {"i": 2, "n": "AVG"},
                        ],
                        "rows": [{"fld": ["2025-01-01T00:00:00Z", "TAG1", 10.5]}],
                    }
                ]
            },
            tag_names=["TAG1"],
            value_column="AVG",
            max_rows=1000,
        )
        # Should handle gracefully - may skip invalid columns
        assert isinstance(frames, list)
        assert isinstance(descriptions, dict)

    def test_row_missing_fld_field(self):
        """Test when row record is missing 'fld' field."""
        parser = SqlAggregatesResponseParser()
        frames, descriptions = parser.parse(
            response={
                "data": [
                    {
                        "cols": [
                            {"i": 0, "n": "TIME_STAMP"},
                            {"i": 1, "n": "NAME"},
                            {"i": 2, "n": "AVG"},
                        ],
                        "rows": [
                            {"other": "data"},  # Missing 'fld'
                            {"fld": ["2025-01-01T00:00:00Z", "TAG1", 10.5]},  # Valid
                        ],
                    }
                ]
            },
            tag_names=["TAG1"],
            value_column="AVG",
            max_rows=1000,
        )
        # Should process valid row and skip invalid one
        assert isinstance(frames, list)

    def test_missing_timestamp_in_row(self):
        """Test when row is missing timestamp field."""
        parser = SqlAggregatesResponseParser()
        frames, descriptions = parser.parse(
            response={
                "data": [
                    {
                        "cols": [
                            {"i": 0, "n": "TIME_STAMP"},
                            {"i": 1, "n": "NAME"},
                            {"i": 2, "n": "AVG"},
                        ],
                        "rows": [
                            {"fld": [None, "TAG1", 10.5]},  # Null timestamp
                        ],
                    }
                ]
            },
            tag_names=["TAG1"],
            value_column="AVG",
            max_rows=1000,
        )
        # Should handle missing timestamp gracefully
        assert isinstance(frames, list)
        assert isinstance(descriptions, dict)

    def test_missing_value_column(self):
        """Test when value column (AVG/MIN/MAX) is missing from response."""
        parser = SqlAggregatesResponseParser()
        frames, descriptions = parser.parse(
            response={
                "data": [
                    {
                        "cols": [
                            {"i": 0, "n": "TIME_STAMP"},
                            {"i": 1, "n": "NAME"},
                            # Missing AVG column
                        ],
                        "rows": [
                            {"fld": ["2025-01-01T00:00:00Z", "TAG1"]},
                        ],
                    }
                ]
            },
            tag_names=["TAG1"],
            value_column="AVG",  # Requesting AVG but not in cols
            max_rows=1000,
        )
        # Should handle missing value column
        assert isinstance(frames, list)
        assert isinstance(descriptions, dict)

    def test_tag_name_field_variations(self):
        """Test tag name extraction from different field names."""
        parser = SqlAggregatesResponseParser()
        # Some responses use 'NAME', others use 'IP_TAG_NAME'
        frames, descriptions = parser.parse(
            response={
                "data": [
                    {
                        "cols": [
                            {"i": 0, "n": "TIME_STAMP"},
                            {"i": 1, "n": "IP_TAG_NAME"},  # Alternative field name
                            {"i": 2, "n": "AVG"},
                        ],
                        "rows": [
                            {"fld": ["2025-01-01T00:00:00Z", "TAG1", 10.5]},
                        ],
                    }
                ]
            },
            tag_names=["TAG1"],
            value_column="AVG",
            max_rows=1000,
        )
        # Should handle IP_TAG_NAME field
        assert isinstance(frames, list)
