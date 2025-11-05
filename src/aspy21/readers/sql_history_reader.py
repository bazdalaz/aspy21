"""SQL history reader for batched multi-tag queries."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

import pandas as pd

from ..query_builder import build_history_sql_query
from .base_reader import BaseReader

if TYPE_CHECKING:
    from ..models import ReaderType

logger = logging.getLogger(__name__)


class SqlHistoryReader(BaseReader):
    """Reader for historical data using SQL endpoint (batches multiple tags)."""

    def can_handle(
        self,
        read_type: ReaderType,
        start: str | None,
        end: str | None,
    ) -> bool:
        """Check if this reader handles SQL history reads."""
        from ..models import ReaderType as RT

        # Handle RAW/INT reads with datasource configured
        return bool(
            read_type in (RT.RAW, RT.INT)
            and self.datasource
            and start is not None
            and end is not None
        )

    def read(
        self,
        tags: list[str],
        start: str | None,
        end: str | None,
        interval: int | None,
        read_type: ReaderType,
        include_status: bool,
        max_rows: int,
        with_description: bool,
    ) -> tuple[list[pd.DataFrame], dict[str, str]]:
        """Read historical data for all tags using SQL endpoint."""
        logger.debug(f"Using SQL endpoint for {read_type.value} read")
        logger.debug(f"Batching {len(tags)} tag(s) in single SQL query")

        # Multiply max_rows by number of tags to ensure each tag gets fair share
        # (SQL max_rows applies to total result set, not per tag)
        batched_max_rows = max_rows * len(tags)
        logger.debug(f"Adjusted max_rows from {max_rows} to {batched_max_rows} for batched query")

        assert start is not None
        assert end is not None

        xml_query = build_history_sql_query(
            tags=tags,  # Pass all tags for batched query
            start=start,
            end=end,
            datasource=self.datasource,
            read_type=read_type,
            interval=interval,
            max_rows=batched_max_rows,
            with_description=with_description,
            include_status=include_status,
        )

        sql_url = f"{self.base_url}/SQL"
        logger.debug(f"POST {sql_url}")
        logger.debug(f"SQL query XML: {xml_query}")

        response = self.http_client.post(
            sql_url, content=xml_query, headers={"Content-Type": "text/xml"}
        )
        response.raise_for_status()

        # Log response details for debugging
        logger.debug(f"Response status: {response.status_code}")
        logger.debug(f"Response content-type: {response.headers.get('content-type', 'unknown')}")
        logger.debug(f"Response content (first 500 chars): {response.text[:500]}")

        # Handle empty response (no data available)
        if not response.text or response.headers.get("content-length") == "0":
            logger.warning(
                "SQL endpoint returned empty response "
                "(possibly unsupported tag type or no data in range)"
            )
            return [], {}

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
            tags,
            include_status=include_status,
            max_rows=max_rows,
        )
        logger.debug(f"Parsed data for {len(frames)} tag(s)")

        return frames, tag_descriptions

    def _parse_multi_tag_sql_response(
        self,
        response: list[dict],
        tag_names: list[str],
        include_status: bool,
        max_rows: int,
    ) -> tuple[list[pd.DataFrame], dict[str, str]]:
        """Parse SQL history response for multiple tags into separate DataFrames."""
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
