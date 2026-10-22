"""SQL history reader for batched multi-tag queries."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from ..errors import AspenSqlError, raise_for_sql_error
from ..query_builder import SqlHistoryQueryBuilder
from .base_reader import BaseReader
from .response_parser import SqlHistoryResponseParser

if TYPE_CHECKING:
    from datetime import tzinfo

    import httpx

    from ..models import ReaderType

logger = logging.getLogger(__name__)


class SqlHistoryReader(BaseReader):
    """Reader for historical data using SQL endpoint (batches multiple tags)."""

    def __init__(
        self,
        base_url: str,
        datasource: str,
        http_client: httpx.Client,
        server_timezone: str | tzinfo | None = None,
        *,
        retries: int = 0,
    ):
        """Initialize SQL history reader with response parser.

        Args:
            base_url: Base URL for the API
            datasource: Datasource name
            http_client: HTTP client for making requests
            server_timezone: Time zone of the IP.21 server, or None for this machine's zone
            retries: How many times to repeat a request that failed transiently
        """
        super().__init__(base_url, datasource, http_client, server_timezone, retries=retries)
        self.parser = SqlHistoryResponseParser()

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
            and bool(self.datasource)
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
        if batched_max_rows != max_rows:
            logger.debug(f"Row limit for {len(tags)} tags: {batched_max_rows} ({max_rows} per tag)")

        assert start is not None
        assert end is not None

        builder = SqlHistoryQueryBuilder()
        xml_query = builder.build(
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

        response = self._post_sql(xml_query)

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
        except ValueError as e:
            message = f"SQL endpoint returned non-JSON response: {response.text[:200]!r}"
            raise AspenSqlError(message) from e

        raise_for_sql_error(sql_response)

        logger.debug(f"SQL response type: {type(sql_response)}")
        response_length = len(sql_response) if isinstance(sql_response, list) else "N/A"
        logger.debug(f"SQL response length: {response_length}")

        # Parse multi-tag SQL response (response="Record" returns clean JSON array)
        frames, tag_descriptions = self.parser.parse(
            sql_response,
            tags,
            include_status=include_status,
            max_rows=max_rows,
        )
        logger.debug(f"Parsed data for {len(frames)} tag(s)")

        return frames, tag_descriptions
