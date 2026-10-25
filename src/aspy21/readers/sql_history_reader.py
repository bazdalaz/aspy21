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
        """Read historical data for all tags using SQL endpoint.

        All tags are read in one query. The server's row limit applies to the whole
        result, which it returns grouped by tag, so the query asks for max_rows rows per
        tag. If the server still returns exactly that many rows, tags late in the result
        may have been cut short; those with fewer than max_rows rows are read again one
        at a time.
        """
        assert start is not None
        assert end is not None
        logger.debug(f"Using SQL endpoint for {read_type.value} read")

        def query(query_tags: list[str], row_limit: int) -> list:
            return self._query(
                query_tags,
                start,
                end,
                interval,
                read_type,
                include_status,
                row_limit,
                with_description,
            )

        batch_limit = max_rows * len(tags)
        if len(tags) > 1:
            logger.debug(f"Row limit for {len(tags)} tags: {batch_limit} ({max_rows} per tag)")
        records = query(tags, batch_limit)
        capped = len(tags) > 1 and max_rows > 0 and len(records) >= batch_limit

        frames, tag_descriptions = self.parser.parse(
            records,
            tags,
            include_status=include_status,
            max_rows=max_rows,
            warn_missing=not capped,
        )

        if capped:
            by_tag = {frame.columns[0]: frame for frame in frames}
            short = [tag for tag in tags if len(by_tag.get(tag, ())) < max_rows]
            if short:
                logger.debug(
                    f"Query returned its row limit ({batch_limit}); "
                    f"reading {len(short)} tag(s) separately: {short}"
                )
            for tag in short:
                tag_frames, descriptions = self.parser.parse(
                    query([tag], max_rows),
                    [tag],
                    include_status=include_status,
                    max_rows=max_rows,
                )
                by_tag.pop(tag, None)
                if tag_frames:
                    by_tag[tag] = tag_frames[0]
                tag_descriptions.update(descriptions)
            frames = [by_tag[tag] for tag in tags if tag in by_tag]

        if max_rows > 0:
            for frame in frames:
                if len(frame) >= max_rows:
                    logger.warning(
                        f"{frame.columns[0]}: returned {max_rows} rows, the row limit; values "
                        f"after {frame.index[-1]} may be missing (raise limit to read them)"
                    )

        logger.debug(f"Parsed data for {len(frames)} tag(s)")
        return frames, tag_descriptions

    def _query(
        self,
        tags: list[str],
        start: str,
        end: str,
        interval: int | None,
        read_type: ReaderType,
        include_status: bool,
        row_limit: int,
        with_description: bool,
    ) -> list:
        """Send one history query and return its records ([] for an empty response)."""
        xml_query = SqlHistoryQueryBuilder().build(
            tags=tags,
            start=start,
            end=end,
            datasource=self.datasource,
            read_type=read_type,
            interval=interval,
            max_rows=row_limit,
            with_description=with_description,
            include_status=include_status,
            timeout=self._server_timeout(),
        )

        logger.debug(f"POST {self.base_url}/SQL")
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
            return []

        try:
            sql_response = response.json()
        except ValueError as e:
            message = f"SQL endpoint returned non-JSON response: {response.text[:200]!r}"
            raise AspenSqlError(message) from e

        raise_for_sql_error(sql_response)

        if not isinstance(sql_response, list):
            # response="Record" returns a list; anything else has no history records
            logger.warning("No data in SQL response")
            return []
        logger.debug(f"SQL response length: {len(sql_response)}")
        return sql_response
