"""Aggregates reader for min, max, avg, and range queries."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from ..errors import AspenSqlError, raise_for_sql_error
from ..query_builder import SqlAggregatesQueryBuilder
from .base_reader import BaseReader
from .response_parser import SqlAggregatesResponseParser

if TYPE_CHECKING:
    from datetime import tzinfo

    import httpx

    from ..models import ReaderType

logger = logging.getLogger(__name__)


class AggregatesReader(BaseReader):
    """Reader for aggregate statistics using SQL aggregates table."""

    def __init__(
        self,
        base_url: str,
        datasource: str,
        http_client: httpx.Client,
        server_timezone: str | tzinfo | None = None,
        *,
        retries: int = 0,
    ):
        """Initialize aggregates reader with response parser.

        Args:
            base_url: Base URL for the API
            datasource: Datasource name
            http_client: HTTP client for making requests
            server_timezone: Time zone of the IP.21 server, or None for this machine's zone
            retries: How many times to repeat a request that failed transiently
        """
        super().__init__(base_url, datasource, http_client, server_timezone, retries=retries)
        self.parser = SqlAggregatesResponseParser()

    def can_handle(
        self,
        read_type: ReaderType,
        start: str | None,
        end: str | None,
    ) -> bool:
        """Check if this reader handles aggregates reads."""
        from ..models import ReaderType as RT

        # Handle aggregate reads (MIN, MAX, AVG, RNG) with datasource configured
        return (
            read_type in (RT.MIN, RT.MAX, RT.AVG, RT.RNG)
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
        """Read aggregate data for all tags using SQL aggregates table.

        Args:
            tags: List of tag names
            start: Start timestamp
            end: End timestamp
            interval: Aggregation period in seconds; if None, one value for the whole range
            read_type: Type of aggregation (MIN, MAX, AVG, RNG)
            include_status: Not supported for aggregates (ignored)
            max_rows: Maximum rows (not typically applicable for aggregates)
            with_description: Include tag descriptions

        Returns:
            Tuple of (list of DataFrames for each tag, dict of tag descriptions)
        """
        logger.debug(f"Using SQL aggregates endpoint for {read_type.value} read")
        if interval:
            logger.debug(
                f"Querying {len(tags)} tag(s) with interval {interval}s from {start} to {end}"
            )
        else:
            logger.debug(f"Querying {len(tags)} tag(s) with period from {start} to {end}")

        assert start is not None
        assert end is not None

        builder = SqlAggregatesQueryBuilder()
        xml_query = builder.build(
            tags=tags,
            start=start,
            end=end,
            datasource=self.datasource,
            read_type=read_type,
            interval=interval,
            with_description=with_description,
            include_status=False,  # Not supported for aggregates
        )

        sql_url = f"{self.base_url}/SQL"
        logger.debug(f"POST {sql_url}")
        logger.debug(f"SQL query XML: {xml_query}")

        response = self._post_sql(xml_query)
        logger.debug(f"Response status: {response.status_code}")
        logger.debug(f"Response content (first 500 chars): {response.text[:500]}")

        try:
            response_data = response.json()
        except ValueError as e:
            message = f"SQL endpoint returned non-JSON response: {response.text[:200]!r}"
            raise AspenSqlError(message) from e

        raise_for_sql_error(response_data)

        # Determine which value column to extract
        from ..models import ReaderType as RT

        value_column_map = {
            RT.MIN: "min",
            RT.MAX: "max",
            RT.AVG: "avg",
            RT.RNG: "rng",
        }
        value_column = value_column_map[read_type]

        # Parse SQL response using aggregates parser
        frames, tag_descriptions = self.parser.parse(
            response=response_data,
            tag_names=tags,
            value_column=value_column,
            max_rows=max_rows,
        )

        return frames, tag_descriptions
