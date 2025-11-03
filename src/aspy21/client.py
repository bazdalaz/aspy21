"""Main client for interacting with Aspen InfoPlus.21 REST API."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from typing import TYPE_CHECKING, cast

import httpx
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from .models import ReaderType
from .query_builder import (
    build_history_sql_query,
    build_read_query,
    build_snapshot_sql_query,
    build_sql_search_query,
)

if TYPE_CHECKING:
    from httpx import Auth

logger = logging.getLogger(__name__)


def configure_logging(level: str | None = None) -> None:
    """Configure logging level for aspy21 library.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
               If None, reads from ASPEN_LOG_LEVEL environment variable.
               Defaults to WARNING if not set.
    """
    if level is None:
        level = os.getenv("ASPEN_LOG_LEVEL", "WARNING")

    numeric_level = getattr(logging, level.upper(), logging.WARNING)
    logger.setLevel(numeric_level)

    # Only add handler if logger doesn't have one already
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)


class AspenClient:
    """Client for Aspen InfoPlus.21 REST API.

    Provides methods to read historical and real-time process data from
    Aspen IP.21 historian via REST API with automatic batching, retries,
    and pandas DataFrame output.

    Supports context manager protocol for automatic resource cleanup.
    """

    def __init__(
        self,
        base_url: str,
        *,
        auth: Auth | tuple[str, str] | None = None,
        timeout: float = 30.0,
        verify_ssl: bool = True,
        datasource: str | None = None,
    ) -> None:
        """Initialize the Aspen client.

        Args:
            base_url: Base URL of the Aspen ProcessData REST API
            auth: Authentication as (username, password) tuple or httpx Auth object.
                  If None, no authentication is used.
            timeout: Request timeout in seconds (default: 30.0)
            verify_ssl: Whether to verify SSL certificates (default: True)
            datasource: Aspen datasource name. If None, uses server default.

        Example:
            Using context manager with authentication:
                >>> with AspenClient(
                ...     base_url="https://aspen.example.com/ProcessData",
                ...     auth=("user", "pass")
                ... ) as client:
                ...     df = client.read(["TAG1"], "2025-01-01", "2025-01-02")

            Without authentication:
                >>> with AspenClient(base_url="http://aspen.example.com/ProcessData") as client:
                ...     df = client.read(["TAG1"], "2025-01-01", "2025-01-02")

            With datasource for search:
                >>> with AspenClient(
                ...     base_url="https://aspen.example.com/ProcessData",
                ...     auth=("user", "pass"),
                ...     datasource="IP21"
                ... ) as client:
                ...     tags = client.search(tag="TEMP*")
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.datasource = datasource or ""  # Empty string = use server default
        self.auth = auth

        self._client = httpx.Client(timeout=timeout, verify=verify_ssl, auth=auth)

        logger.info(f"Initialized AspenClient for {self.base_url}")
        logger.debug(
            f"Config: timeout={timeout}s, verify_ssl={verify_ssl}, datasource={datasource}"
        )

    def __enter__(self) -> AspenClient:
        """Enter context manager.

        Returns:
            self for use in with statement
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager and close connection.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred
        """
        self.close()

    def close(self) -> None:
        """Close the HTTP client connection."""
        self._client.close()

    def _parse_multi_tag_sql_response(
        self,
        response: list[dict],
        tag_names: list[str],
        include_status: bool,
        max_rows: int,
    ) -> tuple[list[pd.DataFrame], dict[str, str]]:
        """Parse SQL history response for multiple tags into separate DataFrames.

        Args:
            response: SQL response as list of record dictionaries (multi-tag data)
            tag_names: List of tag names being queried
            include_status: Whether status field is included in response

        Returns:
            Tuple of (list of DataFrames, dict of tag descriptions)

        SQL response format for multiple tags:
        [
            {"ts": "2025-11-02T00:00:00.000000Z", "name": "TAG1",
             "name->ip_description": "desc1", "value": 22.85, "status": 0},
            {"ts": "2025-11-02T00:01:00.000000Z", "name": "TAG1", "value": 23.0, "status": 0},
            {"ts": "2025-11-02T00:00:00.000000Z", "name": "TAG2", "value": 10.5, "status": 0},
            ...
        ]
        """
        try:
            if not response or not isinstance(response, list):
                logger.warning("No data in SQL response")
                return [], {}

            # Group records by tag name
            from collections import defaultdict

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

    def _parse_sql_history_response(
        self, response: list[dict], tag_name: str, max_rows: int
    ) -> tuple[pd.DataFrame, str]:
        """Parse SQL history response into DataFrame.

        Args:
            response: SQL response as list of record dictionaries
            tag_name: Name of the tag being queried

        Returns:
            Tuple of (DataFrame with timestamp index and tag data, tag description)

        SQL response format:
        [
            {"ts": "2025-11-02T00:00:00.000000Z", "name": "TAG",
             "name->ip_description": "desc", "value": 22.85},
            ...
        ]
        """
        try:
            if not response or not isinstance(response, list):
                logger.warning(f"No data in SQL response for tag {tag_name}")
                return pd.DataFrame(), ""

            # Extract description from first record if available
            description = ""
            if response and "name->ip_description" in response[0]:
                description = response[0]["name->ip_description"] or ""

            # Build DataFrame from records
            rows = []
            for record in response:
                timestamp = pd.to_datetime(record["ts"])
                value = record["value"]
                row = {"time": timestamp, tag_name: value}

                # Include status if present in response
                if "status" in record:
                    row["status"] = record["status"]

                rows.append(row)

            if not rows:
                logger.warning(f"No valid data in SQL response for tag {tag_name}")
                return pd.DataFrame(), description

            df = pd.DataFrame(rows)
            df = df.set_index("time")
            if max_rows > 0:
                df = df.iloc[:max_rows]

            if "status" in df.columns:
                df = df.rename(columns={"status": f"{tag_name}_status"})

            return df, description

        except Exception as e:
            logger.error(f"Error parsing SQL response for tag {tag_name}: {e}")
            logger.debug(f"Response was: {response}")
            return pd.DataFrame(), ""

    def _parse_snapshot_sql_response(
        self,
        response: list[dict],
        tag_names: list[str],
        include_status: bool,
        snapshot_time: pd.Timestamp,
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """Parse SQL snapshot response into DataFrame with descriptions/status."""
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

                if "name->ip_input_value" in record:
                    values[tag_name] = record.get("name->ip_input_value")

                if "name->ip_description" in record and record["name->ip_description"] is not None:
                    descriptions[tag_name] = record["name->ip_description"]

                if include_status and "name->ip_input_quality" in record:
                    status_map[tag_name] = record.get("name->ip_input_quality")

            if not values:
                logger.warning("Snapshot SQL response contained no values")
                return pd.DataFrame(), descriptions

            df = pd.DataFrame([values])
            df.index = pd.DatetimeIndex([snapshot_time], name="time")

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

    def _parse_aspen_response(
        self, response: dict, tag_name: str, include_status: bool, max_rows: int
    ) -> tuple[pd.DataFrame, str]:
        """Parse Aspen REST API response into DataFrame.

        Args:
            response: Response dict from Aspen API
            tag_name: Name of the tag being queried
            include_status: Whether to include status column

        Returns:
            Tuple of (DataFrame with timestamp index and tag data, tag description)

        Aspen API returns:
        {
          "data": [
            {
              "samples": [
                {"t": timestamp_ms, "v": value, "s": status},
                ...
              ]
            }
          ]
        }
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

    @retry(wait=wait_exponential(multiplier=0.5, min=0.5, max=8), stop=stop_after_attempt(3))
    def _fetch(self, xml_query: str) -> dict:
        """Fetch data from API endpoint with automatic retry.

        Args:
            xml_query: XML query string

        Returns:
            JSON response as dictionary

        Raises:
            httpx.HTTPError: If the request fails after retries
        """
        logger.debug(f"POST {self.base_url}")
        logger.debug(f"Query XML: {xml_query}")

        try:
            # Try sending XML as POST body with correct content type
            r = self._client.post(
                self.base_url, content=xml_query, headers={"Content-Type": "text/xml"}
            )
            logger.debug(f"Response status: {r.status_code}")
            logger.debug(f"Response headers: {dict(r.headers)}")

            r.raise_for_status()
            response_data = r.json()

            logger.debug(
                f"Response data keys: {list(response_data.keys()) if response_data else 'empty'}"
            )
            logger.debug(f"Full response: {response_data}")  # Show complete response for debugging

            return response_data

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP {e.response.status_code} error for {self.base_url}")
            logger.error(f"Response body: {e.response.text[:500]}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error: {type(e).__name__}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {type(e).__name__}: {e}")
            raise

    def read(
        self,
        tags: Iterable[str],
        start: str | None = None,
        end: str | None = None,
        interval: int | None = None,
        read_type: ReaderType = ReaderType.INT,
        include_status: bool = False,
        max_rows: int = 100000,
        as_json: bool = True,
        with_description: bool = False,
    ) -> pd.DataFrame | list[dict]:
        """Read process data for multiple tags.

        Args:
            tags: List of tag names to retrieve
            start: Start timestamp (ISO format or compatible string). If omitted, defaults to
                SNAPSHOT read.
            end: End timestamp (ISO format or compatible string). If omitted, defaults to
                SNAPSHOT read.
            interval: Optional interval in seconds for aggregated data (AVG reads)
            read_type: Type of data retrieval (RAW, INT, SNAPSHOT, AVG) (default: INT)
            include_status: Include status column in output (default: False)
            max_rows: Maximum number of rows to return per tag (default: 100000)
            as_json: Return data as list of dictionaries instead of DataFrame (default: True)
            with_description: Include tag descriptions in response (default: False).
                             Note: Some Aspen servers may not support this field.

        Returns:
            If as_json=False: pandas DataFrame with time index and columns for each tag.
                             If include_status=True, includes a 'status' column.
            If as_json=True: List of dictionaries, each containing:
                            - timestamp: ISO format timestamp string
                            - tag: Tag name
                            - description: Tag description (from IP_DESCRIPTION field)
                            - value: Tag value

        Example:
            >>> # JSON output (default)
            >>> client = AspenClient("https://aspen.example.com/ProcessData")
            >>> data = client.read(
            ...     ["ATI111"],
            ...     start="2025-01-01 00:00:00",
            ...     end="2025-01-01 01:00:00"
            ... )
            >>> # Returns: [
            >>> #   {"timestamp": "2025-01-01T00:00:00", "tag": "ATI111",
            >>> #    "description": "Temperature sensor", "value": 25.5},
            >>> #   ...
            >>> # ]

            >>> # DataFrame output
            >>> df = client.read(
            ...     ["ATI111", "AP101.PV"],
            ...     start="2025-01-01 00:00:00",
            ...     end="2025-01-01 01:00:00",
            ...     as_json=False
            ... )
        """
        tags_list = list(tags)
        if not tags_list:
            raise ValueError("At least one tag is required")

        effective_read_type = read_type
        auto_snapshot = False
        history_start: str | None = None
        history_end: str | None = None

        if start is None or end is None:
            if effective_read_type != ReaderType.SNAPSHOT:
                auto_snapshot = True
            effective_read_type = ReaderType.SNAPSHOT
        else:
            history_start = cast(str, start)
            history_end = cast(str, end)

        if effective_read_type == ReaderType.SNAPSHOT:
            if auto_snapshot:
                logger.info(
                    "No start/end provided; defaulting to SNAPSHOT read for %d tag(s)",
                    len(tags_list),
                )
            logger.info(f"Reading {len(tags_list)} tag(s) snapshot values")
        else:
            assert history_start is not None and history_end is not None
            logger.info(
                "Reading %d tag(s) from %s to %s (max_rows=%d)",
                len(tags_list),
                history_start,
                history_end,
                max_rows,
            )

        logger.debug(f"Tags: {tags_list}")
        logger.debug(f"Reader type: {effective_read_type.value}, Interval: {interval}")

        frames: list[pd.DataFrame] = []
        tag_descriptions: dict[str, str] = {}

        if effective_read_type == ReaderType.SNAPSHOT:
            if not self.datasource:
                message = "Datasource is required for SNAPSHOT reads. "
                message += "Please set datasource when creating AspenClient."
                raise ValueError(message)

            xml_query = build_snapshot_sql_query(
                tags=tags_list,
                datasource=self.datasource,
                with_description=with_description or as_json,
            )

            sql_url = f"{self.base_url}/SQL"
            logger.debug(f"POST {sql_url}")
            logger.debug(f"Snapshot SQL query XML: {xml_query}")

            response = self._client.post(
                sql_url, content=xml_query, headers={"Content-Type": "text/xml"}
            )
            response.raise_for_status()

            snapshot_time = pd.Timestamp.utcnow()
            if snapshot_time.tzinfo is None:
                snapshot_time = snapshot_time.tz_localize("UTC")
            else:
                snapshot_time = snapshot_time.tz_convert("UTC")
            snapshot_time = snapshot_time.tz_convert(None)

            try:
                sql_response = response.json()
            except Exception as e:
                logger.error("Failed to parse JSON response from snapshot SQL endpoint")
                logger.error(f"Response status: {response.status_code}")
                logger.error(f"Response headers: {dict(response.headers)}")
                logger.error(f"Response content: {response.text[:1000]}")
                message = "Failed to parse JSON response from snapshot SQL endpoint"
                raise ValueError(message) from e

            snapshot_frame, snapshot_descriptions = self._parse_snapshot_sql_response(
                sql_response,
                tags_list,
                include_status=include_status,
                snapshot_time=snapshot_time,
            )

            if not snapshot_frame.empty:
                frames.append(snapshot_frame)
                tag_descriptions.update(snapshot_descriptions)

        else:
            # Determine if we should use SQL endpoint (for RAW/INT with datasource configured)
            use_sql = effective_read_type in (ReaderType.RAW, ReaderType.INT) and self.datasource

            if use_sql:
                logger.debug(f"Using SQL endpoint for {effective_read_type.value} read")
                logger.debug(f"Batching {len(tags_list)} tag(s) in single SQL query")

                # Multiply max_rows by number of tags to ensure each tag gets fair share
                # (SQL max_rows applies to total result set, not per tag)
                batched_max_rows = max_rows * len(tags_list)
                logger.debug(
                    f"Adjusted max_rows from {max_rows} to {batched_max_rows} for batched query"
                )

                # Use SQL endpoint - batch all tags in a single query for performance
                assert history_start is not None
                assert history_end is not None

                xml_query = build_history_sql_query(
                    tags=tags_list,  # Pass all tags for batched query
                    start=history_start,
                    end=history_end,
                    datasource=self.datasource,
                    read_type=effective_read_type,
                    interval=interval,
                    max_rows=batched_max_rows,
                    with_description=with_description or as_json,
                    include_status=include_status,
                )

                sql_url = f"{self.base_url}/SQL"
                logger.debug(f"POST {sql_url}")
                logger.debug(f"SQL query XML: {xml_query}")

                response = self._client.post(
                    sql_url, content=xml_query, headers={"Content-Type": "text/xml"}
                )
                response.raise_for_status()

                # Log response details for debugging
                logger.debug(f"Response status: {response.status_code}")
                logger.debug(
                    f"Response content-type: {response.headers.get('content-type', 'unknown')}"
                )
                logger.debug(f"Response content (first 500 chars): {response.text[:500]}")

                # Handle empty response (no data available)
                if not response.text or response.headers.get("content-length") == "0":
                    logger.warning(
                        "SQL endpoint returned empty response "
                        "(possibly unsupported tag type or no data in range)"
                    )
                    if as_json:
                        return []
                    return pd.DataFrame()

                try:
                    sql_response = response.json()
                except Exception as e:
                    logger.error("Failed to parse JSON response from SQL endpoint")
                    logger.error(f"Response status: {response.status_code}")
                    logger.error(f"Response headers: {dict(response.headers)}")
                    logger.error(f"Response content: {response.text[:1000]}")
                    raise ValueError(
                        f"SQL endpoint returned non-JSON response: {response.text[:200]}"
                    ) from e

                logger.debug(f"SQL response type: {type(sql_response)}")
                response_length = len(sql_response) if isinstance(sql_response, list) else "N/A"
                logger.debug(f"SQL response length: {response_length}")

                # Parse multi-tag SQL response (response="Record" returns clean JSON array)
                frames, tag_descriptions = self._parse_multi_tag_sql_response(
                    sql_response,
                    tags_list,
                    include_status=include_status,
                    max_rows=max_rows,
                )
                logger.debug(f"Parsed data for {len(frames)} tag(s)")

            else:
                # Use original XML endpoint - still needs to loop over tags
                logger.debug(f"Using XML endpoint for {effective_read_type.value} read")
                for tag_idx, tag in enumerate(tags_list, 1):
                    logger.debug(f"Processing tag {tag_idx}/{len(tags_list)}: {tag}")

                    assert history_start is not None
                    assert history_end is not None

                    xml_query = build_read_query(
                        tag=tag,
                        start=history_start,
                        end=history_end,
                        read_type=effective_read_type,
                        interval=interval,
                        datasource=self.datasource,
                        max_rows=max_rows,
                        with_description=with_description,
                    )

                    response = self._fetch(xml_query)
                    logger.debug(f"Received response for tag: {tag}")

                    # Parse the Aspen-style response
                    df, description = self._parse_aspen_response(
                        response,
                        tag,
                        include_status=include_status,
                        max_rows=max_rows,
                    )
                    logger.debug(f"Parsed {len(df)} data points for tag {tag}")

                    if not df.empty:
                        frames.append(df)
                        if description:
                            tag_descriptions[tag] = description

        if not frames:
            logger.warning("No data returned from API")
            if as_json:
                return []
            return pd.DataFrame()

        # Merge frames by index (time), combining columns for different tags
        out = pd.concat(frames, axis=1)
        out = out.sort_index()

        if include_status:
            ordered_cols: list[str] = []
            for tag in tags_list:
                if tag in out.columns:
                    ordered_cols.append(tag)
                    status_col = f"{tag}_status"
                    if status_col in out.columns:
                        ordered_cols.append(status_col)
            remaining_cols = [col for col in out.columns if col not in ordered_cols]
            if ordered_cols:
                out = out.loc[:, ordered_cols + remaining_cols]

        logger.info(f"Successfully retrieved {len(out)} rows for {len(out.columns)} column(s)")

        # Convert to JSON format if requested
        if as_json:
            json_data: list[dict] = []
            for idx, row in out.iterrows():
                # Iterate through each tag (column) in this row
                for tag in tags_list:
                    if tag in row.index:
                        value = row[tag]
                        # Skip NaN values - use isinstance check to avoid Series.__bool__ issue
                        if isinstance(value, (int, float, str)) and pd.notna(value):
                            # idx is pandas Timestamp, which has isoformat method
                            # type: ignore is needed because iterrows() returns Hashable for index
                            ts = (
                                idx.isoformat()  # type: ignore[union-attr]
                                if hasattr(idx, "isoformat")
                                else str(idx)
                            )
                            record: dict[str, object] = {
                                "timestamp": ts,
                                "tag": tag,
                                "description": tag_descriptions.get(tag, ""),
                                "value": value,
                            }
                            if include_status:
                                status_col = f"{tag}_status"
                                if status_col in row.index:
                                    status_value = row.get(status_col)
                                    if isinstance(status_value, (int, float, str)) and pd.notna(
                                        status_value
                                    ):
                                        record["status"] = status_value
                            json_data.append(record)
            logger.debug(f"Converted to {len(json_data)} JSON records")
            return json_data

        return out

    def _search_by_sql(
        self,
        description: str,
        tag_pattern: str = "*",
        max_results: int = 10000,
        return_desc: bool = True,
    ) -> list[dict[str, str]] | list[str]:
        """Search for tags by description using SQL endpoint.

        This is an internal method that uses the Aspen SQL endpoint to search
        by tag description (ip_description field) and optionally by tag name.
        Both filters are applied server-side in the SQL WHERE clause.

        Args:
            description: Description pattern to search for (supports * wildcards,
                        converted to SQL % wildcards)
            tag_pattern: Tag name pattern to filter by (supports * and ? wildcards,
                        converted to SQL % and _ wildcards). Use "*" for all tags.
            max_results: Maximum number of results to return (default: 10000)

        Returns:
            List of dictionaries with 'name' and 'description' keys

        Raises:
            ValueError: If datasource is not configured
        """
        if not self.datasource:
            raise ValueError(
                "Datasource is required for SQL search. "
                "Please set datasource when creating AspenClient: "
                "AspenClient(base_url=..., datasource='your_datasource')"
            )

        # Build XML query for SQL endpoint
        xml = build_sql_search_query(
            datasource=self.datasource,
            description=description,
            tag_pattern=tag_pattern,
            max_results=max_results,
        )

        logger.debug(f"SQL query XML: {xml}")

        sql_url = f"{self.base_url}/SQL"
        logger.info(f"SQL request: POST {sql_url}")

        try:
            response = self._client.post(sql_url, content=xml, headers={"Content-Type": "text/xml"})

            logger.debug(f"Response status: {response.status_code}")
            response.raise_for_status()

            data = response.json()
            logger.debug(f"SQL response keys: {list(data.keys())}")

            # Parse SQL response format
            # Expected: {"data": [{"g": "...", "r": "D", "cols": [...], "rows": [{"fld": [...]}]}]}
            if "data" not in data or not isinstance(data["data"], list):
                logger.warning("Unexpected SQL response structure")
                logger.debug(f"Full response: {data}")
                return []

            data_array = data["data"]
            if not data_array or len(data_array) == 0:
                logger.info("SQL search returned 0 results")
                return []

            # Get first result set
            result_set = data_array[0]
            if not isinstance(result_set, dict):
                logger.warning("Unexpected result set structure")
                return []

            # Check for errors
            if "result" in result_set:
                result = result_set["result"]
                if isinstance(result, dict) and result.get("er", 0) != 0:
                    error_msg = result.get("es", "Unknown error")
                    logger.error(f"API error from SQL endpoint: {error_msg}")
                    raise ValueError(f"SQL API error: {error_msg}")

            # Get rows array
            rows = result_set.get("rows", [])
            if not rows:
                logger.info("SQL search returned 0 results")
                return []

            logger.debug(f"Found {len(rows)} rows in SQL response")

            results = []
            for row in rows:
                if not isinstance(row, dict) or "fld" not in row:
                    continue

                # Extract field values: fld is array of {"i": index, "v": value}
                fields = row["fld"]
                if len(fields) < 2:
                    continue

                tag_name = fields[0].get("v", "")
                tag_desc = fields[1].get("v", "")

                # No client-side filtering - SQL WHERE clause handles name and description
                if return_desc:
                    results.append({"name": tag_name, "description": tag_desc})
                else:
                    results.append(tag_name)

            logger.info(f"Found {len(results)} matching tags via SQL")
            return results[:max_results]

        except Exception as e:
            logger.error(f"Error in SQL search: {type(e).__name__}: {e}")
            raise

    def search(
        self,
        tag: str = "*",
        description: str | None = None,
        case_sensitive: bool = False,
        max_results: int = 10000,
        return_desc: bool = True,
    ) -> list[dict[str, str]] | list[str]:
        """Search for tags by name pattern and/or description.

        Supports wildcards:
        - '*' matches any number of characters
        - '?' matches exactly one character

        When description parameter is provided, uses SQL endpoint with server-side
        filtering for both tag name and description. Otherwise uses Browse endpoint
        for tag name only.

        Args:
            tag: Tag name pattern with wildcards (e.g., "TEMP*", "?AI_10?", "*" for all tags).
                 Defaults to "*" (all tags).
            description: Description pattern to filter by (case-insensitive substring match).
                         When provided, uses SQL endpoint for server-side search.
            case_sensitive: Whether tag name matching should be case-sensitive (default: False).
                           Only applies to Browse endpoint (tag-only search).
            max_results: Maximum number of results to return (default: 10000)
            return_desc: Whether to return descriptions (default: True).
                        If True, returns list of dicts with 'name' and 'description'.
                        If False, returns list of tag name strings only.

        Returns:
            If return_desc=True: List of dictionaries with 'name' and 'description' keys.
            If return_desc=False: List of tag name strings.

        Raises:
            ValueError: If datasource is not configured

        Example:
            >>> # Find all temperature tags with descriptions
            >>> tags = client.search(tag="TEMP*")
            >>> # Returns: [{"name": "TEMP_101", "description": "Reactor temp"}, ...]
            >>>
            >>> # Get just tag names without descriptions
            >>> tag_names = client.search(tag="TEMP*", return_desc=False)
            >>> # Returns: ["TEMP_101", "TEMP_102", ...]
            >>>
            >>> # Search by description only
            >>> tags = client.search(description="reactor")
            >>>
            >>> # Combine name and description
            >>> tags = client.search(tag="AI_1*", description="pressure")
            >>>
            >>> # Process results with descriptions
            >>> for tag in tags:
            ...     print(f"{tag['name']}: {tag['description']}")
        """
        import urllib.parse

        if not self.datasource:
            raise ValueError(
                "Datasource is required for search. "
                "Please set datasource when creating AspenClient: "
                "AspenClient(base_url=..., datasource='your_datasource')"
            )

        logger.info(f"Searching tags: pattern={tag}, description={description}")

        # If description is provided, use SQL endpoint for efficient server-side search
        if description:
            return self._search_by_sql(
                description=description,
                tag_pattern=tag,
                max_results=max_results,
                return_desc=return_desc,
            )

        # Otherwise, use Browse endpoint for tag name search
        # Use Any type for results list to handle both dict and str
        from typing import Any

        results: list[Any] = []

        # Build query parameters
        # Note: The key is "dataSource" (camelCase)
        params = {
            "dataSource": self.datasource,
            "tag": tag,
            "max": max_results,
            "getTrendable": 0,
        }

        # Construct Browse endpoint URL with manually encoded query string
        # We need to keep * unencoded for wildcard matching
        # Following tagreader's approach: encode with safe="*"
        encoded_params = urllib.parse.urlencode(params, safe="*", quote_via=urllib.parse.quote)
        browse_url = f"{self.base_url}/Browse?{encoded_params}"

        logger.info(f"Browse request: GET {browse_url}")
        logger.debug(f"Query params: {params}")

        try:
            # Make GET request to Browse endpoint
            # URL already contains query string, so don't pass params again
            response = self._client.get(browse_url)

            # Log the actual request details
            logger.debug(f"Request URL: {response.request.url}")
            logger.debug(f"Request method: {response.request.method}")
            logger.debug(f"Response status: {response.status_code}")

            response.raise_for_status()
            data = response.json()

            logger.debug(f"Browse response keys: {list(data.keys())}")

            # Check for API error response
            if "data" in data and isinstance(data["data"], dict):
                data_obj = data["data"]
                logger.debug(f"data['data'] keys: {list(data_obj.keys())}")

                # Check for error in result
                if "result" in data_obj:
                    result = data_obj["result"]
                    if isinstance(result, dict) and result.get("er", 0) != 0:
                        error_msg = result.get("es", "Unknown error")
                        logger.error(f"API error from Browse endpoint: {error_msg}")
                        raise ValueError(f"Browse API error: {error_msg}")

                # Check if tags key exists
                if "tags" not in data_obj:
                    logger.warning("No 'tags' key in response - search returned no results")
                    logger.debug(f"Full response: {data}")
                    return []

                tags_data = data_obj["tags"]
            else:
                logger.error(f"Unexpected response structure: {data}")
                return []

            logger.debug(f"tags_data type: {type(tags_data)}, length: {len(tags_data)}")

            if not tags_data:
                logger.info("Search returned 0 tags")
                return []

            for tag_entry in tags_data:
                tag_name = tag_entry.get("t", "")
                # Response contains "m" (map type) like "IP_ANALOGMAP", "KPI_VALUEMAP"
                # and optionally "n" (description). Use "n" if available, otherwise "m"
                tag_desc = tag_entry.get("n", tag_entry.get("m", ""))

                # Apply case-insensitive filtering if needed
                if (
                    not case_sensitive
                    and tag
                    and "*" not in tag
                    and "?" not in tag
                    and tag.lower() not in tag_name.lower()
                ):
                    continue

                if return_desc:
                    results.append({"name": tag_name, "description": tag_desc})
                else:
                    results.append(tag_name)

            logger.info(f"Found {len(results)} matching tags")
            return results[:max_results]

        except Exception as e:
            logger.error(f"Error searching tags: {type(e).__name__}: {e}")
            raise
