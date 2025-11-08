"""Response parsers for converting API responses to DataFrames.

This module implements the Strategy Pattern for parsing different API response formats.
Each parser handles a specific response format (SQL snapshot, SQL history, XML history).
"""

from __future__ import annotations

import logging
from abc import ABC
from collections import defaultdict

import pandas as pd

logger = logging.getLogger(__name__)


class ResponseParser(ABC):  # noqa: B024
    """Abstract base class for response parsing strategies.

    Each parser implements a specific strategy for parsing API responses
    into pandas DataFrames with metadata (descriptions, status).

    Note: Subclasses implement parse() with signatures specific to their
    response format. The varying signatures are intentional as each parser
    handles fundamentally different API response structures.
    """

    pass


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
        try:
            if not response or not isinstance(response, list):
                logger.warning("No data in snapshot SQL response")
                return pd.DataFrame(), {}

            values: dict[str, object] = {}
            descriptions: dict[str, str] = {}
            status_map: dict[str, object] = {}

            for record in response:
                tag_name = record.get("name")
                if not tag_name or tag_name not in tag_names:
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

        except Exception as e:
            logger.error(f"Error parsing snapshot SQL response: {e}")
            logger.debug(f"Response was: {response}")
            return pd.DataFrame(), {}


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
    ) -> tuple[list[pd.DataFrame], dict[str, str]]:
        """Parse SQL history response for multiple tags into separate DataFrames.

        Args:
            response: SQL query response as list of records
            tag_names: List of tag names to extract
            include_status: Whether to include status column
            max_rows: Maximum rows per tag (0 = unlimited)

        Returns:
            Tuple of (list of DataFrames, tag descriptions dict)
        """
        try:
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

                tag_records[tag_name].append(record)

                # Extract description from first record of each tag
                if tag_name not in tag_descriptions and "name->ip_description" in record:
                    tag_descriptions[tag_name] = record["name->ip_description"] or ""

            # Build DataFrame for each tag
            frames = []
            for tag_name in tag_names:
                records = tag_records.get(tag_name, [])

                if not records:
                    logger.warning(f"No data in SQL response for tag {tag_name}")
                    continue

                # Build DataFrame from records
                rows = []
                for record in records:
                    timestamp = pd.to_datetime(record["ts"])
                    value = record["value"]
                    row = {"time": timestamp, tag_name: value}

                    # Include status if present in response
                    if include_status and "status" in record:
                        row["status"] = record["status"]

                    rows.append(row)

                if rows:
                    df = pd.DataFrame(rows)
                    df = df.set_index("time")
                    if max_rows > 0:
                        df = df.iloc[:max_rows]
                    if include_status and "status" in df.columns:
                        df = df.rename(columns={"status": f"{tag_name}_status"})
                    frames.append(df)
                    logger.debug(f"Parsed {len(df)} data points for tag {tag_name}")

            return frames, tag_descriptions

        except Exception as e:
            logger.error(f"Error parsing multi-tag SQL response: {e}")
            logger.debug(f"Response was: {response}")
            return [], {}


class XmlHistoryResponseParser(ResponseParser):
    """Parser for XML-style history responses.

    Parses XML REST API responses containing historical data for a single tag.
    Returns a single DataFrame.
    """

    def parse(
        self, response: dict, tag_name: str, include_status: bool, max_rows: int
    ) -> tuple[pd.DataFrame, str]:
        """Parse Aspen REST API response into DataFrame.

        Args:
            response: XML-style API response as dict
            tag_name: Tag name being queried
            include_status: Whether to include status column
            max_rows: Maximum rows to return (0 = unlimited)

        Returns:
            Tuple of (DataFrame, description string)
        """
        try:
            # Get data array
            data = response.get("data", [])
            if not data or not isinstance(data, list):
                logger.warning(f"No data array in response for tag {tag_name}")
                return pd.DataFrame(), ""

            # Get first element (should contain samples)
            tag_data = data[0] if len(data) > 0 else {}

            # Extract description if available (from IP_DESCRIPTION field)
            description = ""
            if "l" in tag_data and isinstance(tag_data["l"], list) and len(tag_data["l"]) > 0:
                # "l" contains list of field values, IP_DESCRIPTION is second field if requested
                fields = tag_data["l"]
                if len(fields) > 1:
                    description = fields[1] if fields[1] is not None else ""

            # Check for errors in samples
            samples = tag_data.get("samples", [])
            if samples and isinstance(samples, list) and len(samples) > 0:
                first_sample = samples[0]
                # Check if first sample contains an error
                if "er" in first_sample and first_sample.get("er", 0) != 0:
                    error_msg = first_sample.get("es", "Unknown error")
                    logger.warning(f"API error for tag {tag_name}: {error_msg}")
                    return pd.DataFrame(), description

            if not samples:
                logger.warning(f"No samples found for tag {tag_name}")
                return pd.DataFrame(), description

            # Build DataFrame
            rows = []
            for sample in samples:
                # Skip error samples
                if "er" in sample:
                    continue

                row = {
                    "time": pd.to_datetime(sample["t"], unit="ms", utc=True).tz_convert(None),
                    tag_name: sample.get("v"),
                }
                if include_status:
                    row[f"{tag_name}_status"] = sample.get("s", 0)
                rows.append(row)

            if not rows:
                logger.warning(f"No valid data samples for tag {tag_name}")
                return pd.DataFrame(), description

            df = pd.DataFrame(rows)
            if not df.empty:
                df = df.set_index("time")
                if max_rows > 0:
                    df = df.iloc[:max_rows]

            return df, description

        except Exception as e:
            logger.error(f"Error parsing response for tag {tag_name}: {e}")
            logger.debug(f"Response was: {response}")
            return pd.DataFrame(), ""


class SqlAggregatesResponseParser(ResponseParser):
    """Parser for SQL aggregates table responses.

    Parses SQL aggregates responses containing min, max, avg, or rng values.
    """

    def parse(
        self,
        response: list[dict],
        tag_names: list[str],
        value_column: str,  # "min", "max", "avg", or "rng"
        max_rows: int,
    ) -> tuple[list[pd.DataFrame], dict[str, str]]:
        """Parse SQL aggregates response.

        Args:
            response: SQL query response as list of records
            tag_names: List of tag names to extract
            value_column: Name of the value column (min, max, avg, or rng)
            max_rows: Maximum rows per tag (0 = unlimited)

        Returns:
            Tuple of (list of DataFrames, dict of tag descriptions)
        """
        from collections import defaultdict

        try:
            logger.debug("SqlAggregatesResponseParser.parse called")
            logger.debug(f"Response type: {type(response)}")
            logger.debug(f"Response content: {response}")
            logger.debug(f"Tag names: {tag_names}")
            logger.debug(f"Value column: {value_column}")

            if not response:
                logger.warning("No data in SQL aggregates response")
                return [], {}

            # Group records by tag name
            tag_records: dict[str, list[dict]] = defaultdict(list)
            tag_descriptions: dict[str, str] = {}

            for i, record in enumerate(response):
                logger.debug(f"Processing record {i}: type={type(record)}, content={record}")
                tag_name = record.get("name")
                if not tag_name:
                    logger.warning(f"Record {i} has no 'name' field")
                    continue

                tag_records[tag_name].append(record)

                # Extract description from first record of each tag
                if tag_name not in tag_descriptions and "name->ip_description" in record:
                    tag_descriptions[tag_name] = record["name->ip_description"] or ""

            # Build DataFrame for each tag
            frames = []
            for tag_name in tag_names:
                records = tag_records.get(tag_name, [])

                if not records:
                    logger.warning(f"No data in SQL aggregates response for tag {tag_name}")
                    continue

                # Build DataFrame from records
                rows = []
                for record in records:
                    timestamp = pd.to_datetime(record["ts"])
                    value = record[value_column]  # Use the specified column name
                    row = {"time": timestamp, tag_name: value}
                    rows.append(row)

                if rows:
                    df = pd.DataFrame(rows)
                    df = df.set_index("time")
                    if max_rows > 0:
                        df = df.iloc[:max_rows]
                    frames.append(df)
                    logger.debug(f"Parsed {len(df)} aggregate records for tag {tag_name}")

            return frames, tag_descriptions

        except Exception as e:
            logger.error(f"Error parsing SQL aggregates response: {e}")
            logger.debug(f"Response was: {response}")
            return [], {}
