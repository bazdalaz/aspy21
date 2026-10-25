"""Response parsers for converting API responses to DataFrames.

This module implements the Strategy Pattern for parsing different API response formats.
Each parser handles a specific response format (SQL snapshot, SQL history, SQL aggregates).
"""

from __future__ import annotations

import logging
from abc import ABC
from collections import defaultdict
from typing import Any

import pandas as pd

from ..errors import AspenSqlError
from ..utils import tag_key

logger = logging.getLogger(__name__)


def _first_not_none(record: dict, *keys: str) -> Any:
    """Return the first value for keys that is not None (0 and "" are valid values)."""
    for key in keys:
        value = record.get(key)
        if value is not None:
            return value
    return None


def _to_datetimes(values: list) -> pd.DatetimeIndex | list:
    """Parse response timestamps in one call (parsing them one by one is far slower).

    IP.21 returns ISO 8601 timestamps; any other format falls back to parsing each value.
    """
    try:
        return pd.to_datetime(values, format="ISO8601")
    except (ValueError, TypeError):
        return [pd.to_datetime(value) for value in values]


class ResponseParser(ABC):  # noqa: B024
    """Abstract base class for response parsing strategies.

    Each parser implements a specific strategy for parsing API responses
    into pandas DataFrames with metadata (descriptions, status).

    Note: Subclasses implement parse() with signatures specific to their
    response format. The varying signatures are intentional as each parser
    handles fundamentally different API response structures.
    """


class SqlSnapshotResponseParser(ResponseParser):
    """Parser for SQL snapshot responses.

    Parses SQL query responses containing current (snapshot) values for multiple tags.
    Returns a single-row DataFrame at the snapshot timestamp.
    """

    def parse(
        self,
        response: list[dict],
        tag_names: list[str],
        include_status: bool,
        snapshot_time: pd.Timestamp,
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """Parse SQL snapshot response into DataFrame with descriptions/status.

        Args:
            response: SQL query response as list of records
            tag_names: List of tag names to extract
            include_status: Whether to include status column
            snapshot_time: Timestamp to use for the snapshot

        Returns:
            Tuple of (DataFrame with single row, tag descriptions dict)
        """
        if not response or not isinstance(response, list):
            logger.warning("No data in snapshot SQL response")
            return pd.DataFrame(), {}

        values: dict[str, object] = {}
        descriptions: dict[str, str] = {}
        status_map: dict[str, object] = {}

        requested = {tag_key(name): name for name in tag_names}
        for record in response:
            tag_name = requested.get(tag_key(record.get("name")))
            if not tag_name:
                continue

            # Extract value
            if "name->ip_input_value" in record:
                values[tag_name] = record.get("name->ip_input_value")

            # Extract description
            if "name->ip_description" in record and record["name->ip_description"] is not None:
                descriptions[tag_name] = record["name->ip_description"]

            # Extract status if requested
            if include_status and "name->ip_input_quality" in record:
                status_map[tag_name] = record.get("name->ip_input_quality")

        if not values:
            logger.warning("Snapshot SQL response contained no values")
            return pd.DataFrame(), descriptions

        # Build single-row DataFrame at snapshot time
        df = pd.DataFrame([values])
        df.index = pd.DatetimeIndex([snapshot_time], name="time")

        # Add status columns if requested
        if include_status and status_map:
            status_df = pd.DataFrame([status_map])
            status_df.index = df.index
            status_df.columns = [f"{col}_status" for col in status_df.columns]
            df = pd.concat([df, status_df], axis=1)

        return df, descriptions


class SqlHistoryResponseParser(ResponseParser):
    """Parser for SQL history responses.

    Parses SQL query responses containing historical data for multiple tags.
    Returns a list of DataFrames (one per tag).
    """

    def parse(
        self,
        response: list[dict],
        tag_names: list[str],
        include_status: bool,
        max_rows: int,
        warn_missing: bool = True,
    ) -> tuple[list[pd.DataFrame], dict[str, str]]:
        """Parse SQL history response for multiple tags into separate DataFrames.

        Args:
            response: SQL query response as list of records
            tag_names: List of tag names to extract
            include_status: Whether to include status column
            max_rows: Maximum rows per tag (0 = unlimited)
            warn_missing: Log a warning for each tag without data

        Returns:
            Tuple of (list of DataFrames, tag descriptions dict)
        """
        if not response or not isinstance(response, list):
            logger.warning("No data in SQL response")
            return [], {}

        # Group records by tag name
        tag_records = defaultdict(list)
        tag_descriptions = {}

        for record in response:
            tag_name = record.get("name")
            if not tag_name:
                continue
            key = tag_key(tag_name)

            tag_records[key].append(record)

            # Extract description from first record of each tag
            if key not in tag_descriptions and "name->ip_description" in record:
                tag_descriptions[key] = record["name->ip_description"] or ""

        # Build DataFrame for each tag
        frames = []
        descriptions = {
            name: tag_descriptions[tag_key(name)]
            for name in tag_names
            if tag_key(name) in tag_descriptions
        }
        for tag_name in tag_names:
            records = tag_records.get(tag_key(tag_name), [])

            if not records:
                if warn_missing:
                    logger.warning(f"No data in SQL response for tag {tag_name}")
                continue

            # Build DataFrame from records
            columns = {
                "time": _to_datetimes([record["ts"] for record in records]),
                tag_name: [record["value"] for record in records],
            }
            # Include status if present in response (NaN for records without one)
            if include_status and any("status" in record for record in records):
                columns[f"{tag_name}_status"] = [
                    record.get("status", float("nan")) for record in records
                ]

            df = pd.DataFrame(columns).set_index("time")
            if max_rows > 0:
                df = df.iloc[:max_rows]
            frames.append(df)
            logger.debug(f"Parsed {len(df)} data points for tag {tag_name}")

        return frames, descriptions


class SqlAggregatesResponseParser(ResponseParser):
    """Parser for SQL aggregates table responses.

    Parses SQL aggregates responses containing min, max, avg, or rng values.
    """

    def parse(
        self,
        response: dict | list,
        tag_names: list[str],
        value_column: str,  # "min", "max", "avg", or "rng"
        max_rows: int,
    ) -> tuple[list[pd.DataFrame], dict[str, str]]:
        """Parse SQL aggregates response.

        Args:
            response: SQL query response (can be dict with "data" wrapper or list of records)
            tag_names: List of tag names to extract
            value_column: Name of the value column (min, max, avg, or rng)
            max_rows: Maximum rows per tag (0 = unlimited)

        Returns:
            Tuple of (list of DataFrames, dict of tag descriptions)
        """
        from collections import defaultdict

        logger.debug(
            f"Parsing aggregates response for {len(tag_names)} tag(s), column {value_column}"
        )

        if not response:
            logger.warning("Empty SQL aggregates response")
            return [], {}

        # Handle SQL response format: {"data": [{"cols": [...], "rows": [...]}]}
        records = []
        if isinstance(response, dict):
            # A malformed response is an error, not "no data"
            if "data" not in response:
                keys = list(response.keys())
                raise AspenSqlError(f"Unexpected aggregates response: no 'data' field, keys {keys}")

            data_array = response["data"]

            if not isinstance(data_array, list):
                kind = type(data_array).__name__
                raise AspenSqlError(f"Unexpected aggregates response: 'data' is {kind}")
            if not data_array:
                logger.warning("Empty 'data' array in SQL aggregates response")
                return [], {}

            # Get first result set
            result_set = data_array[0]

            if not isinstance(result_set, dict):
                kind = type(result_set).__name__
                raise AspenSqlError(f"Unexpected aggregates response: result set is {kind}")

            # Extract column definitions and row data
            cols = result_set.get("cols", [])
            rows = result_set.get("rows", [])

            logger.debug(f"Found {len(cols)} columns and {len(rows)} rows")

            if not cols or not rows:
                logger.warning("No columns or rows in SQL aggregates response")
                return [], {}

            # Build column name mapping from index to name
            col_map = {}
            for col in cols:
                if isinstance(col, dict) and "i" in col and "n" in col:
                    col_map[col["i"]] = col["n"]

            # Convert rows to list of dicts
            invalid_rows = []
            for row in rows:
                if not isinstance(row, dict) or "fld" not in row:
                    invalid_rows.append(row)
                    continue

                fields = row["fld"]
                record = {}

                for field in fields:
                    if isinstance(field, dict) and "i" in field and "v" in field:
                        field_idx = field["i"]
                        field_value = field["v"]
                        if field_idx in col_map:
                            record[col_map[field_idx]] = field_value

                if record:
                    records.append(record)

            if invalid_rows:
                logger.warning(
                    f"Skipped {len(invalid_rows)} row(s) with invalid structure, "
                    f"e.g. {invalid_rows[0]}"
                )
            logger.debug(f"Extracted {len(records)} records from SQL response")

        elif isinstance(response, list):
            records = [record for record in response if isinstance(record, dict)]
        else:
            kind = type(response).__name__
            raise AspenSqlError(f"Unexpected aggregates response type: {kind}")

        if not records:
            logger.warning("No records extracted from SQL aggregates response")
            return [], {}

        # Group records by tag name
        tag_records: dict[str, list[dict]] = defaultdict(list)
        tag_descriptions: dict[str, str] = {}

        unnamed = []
        for record in records:
            # Tag name might be in different fields depending on query structure
            tag_name = record.get("name") or record.get("ip_tag_name")
            if not tag_name:
                unnamed.append(record)
                continue
            key = tag_key(tag_name)

            tag_records[key].append(record)

            # Extract description if available
            desc_field = record.get("name->ip_description") or record.get("ip_description")
            if key not in tag_descriptions and desc_field:
                tag_descriptions[key] = desc_field or ""

        if unnamed:
            logger.warning(
                f"Skipped {len(unnamed)} record(s) without a tag name field, "
                f"e.g. fields {list(unnamed[0].keys())}"
            )
        logger.debug(f"Grouped records into {len(tag_records)} tags")

        # Build DataFrame for each tag
        frames = []
        descriptions = {
            name: tag_descriptions[tag_key(name)]
            for name in tag_names
            if tag_key(name) in tag_descriptions
        }
        for tag_name in tag_names:
            records_for_tag = tag_records.get(tag_key(tag_name), [])

            if not records_for_tag:
                logger.warning(f"No data in SQL aggregates response for tag {tag_name}")
                continue

            # Build DataFrame from records
            timestamps = []
            values = []
            no_timestamp = 0
            no_value: list[str] = []  # field names of the first record without a value
            no_value_count = 0
            for record in records_for_tag:
                # Timestamp might be in different fields
                ts_value = _first_not_none(record, "ts", "ip_trend_time")
                if ts_value is None:
                    no_timestamp += 1
                    continue

                # Value column might have prefix
                value = _first_not_none(record, value_column, f"ip_{value_column}")
                if value is None:
                    no_value_count += 1
                    no_value = no_value or list(record.keys())
                    continue

                timestamps.append(ts_value)
                values.append(value)

            if no_timestamp:
                logger.warning(f"Skipped {no_timestamp} record(s) without timestamp for {tag_name}")
            if no_value_count:
                logger.warning(
                    f"Skipped {no_value_count} record(s) without value column '{value_column}' "
                    f"for {tag_name}, e.g. fields {no_value}"
                )

            if values:
                df = pd.DataFrame({"time": _to_datetimes(timestamps), tag_name: values})
                df = df.set_index("time")
                if max_rows > 0:
                    df = df.iloc[:max_rows]
                frames.append(df)
                logger.debug(f"Parsed {len(df)} aggregate records for tag {tag_name}")
            else:
                logger.warning(f"No valid rows extracted for tag {tag_name}")

        logger.debug(f"Parsed {len(frames)} DataFrame(s) from aggregates response")
        return frames, descriptions
