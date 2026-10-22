"""Snapshot reader for current values."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from ..errors import AspenSqlError, raise_for_sql_error
from ..query_builder import SqlSnapshotQueryBuilder
from ..utils import server_now
from .base_reader import BaseReader
from .response_parser import SqlSnapshotResponseParser

if TYPE_CHECKING:
    from datetime import tzinfo

    import httpx

    from ..models import ReaderType

logger = logging.getLogger(__name__)


class SnapshotReader(BaseReader):
    """Reader for snapshot (current value) reads using SQL endpoint."""

    def __init__(
        self,
        base_url: str,
        datasource: str,
        http_client: httpx.Client,
        server_timezone: str | tzinfo | None = None,
        *,
        retries: int = 0,
    ):
        """Initialize snapshot reader with response parser.

        Args:
            base_url: Base URL for the API
            datasource: Datasource name
            http_client: HTTP client for making requests
            server_timezone: Time zone of the IP.21 server, or None for this machine's zone
            retries: How many times to repeat a request that failed transiently
        """
        super().__init__(base_url, datasource, http_client, server_timezone, retries=retries)
        self.parser = SqlSnapshotResponseParser()

    def can_handle(
        self,
        read_type: ReaderType,
        start: str | None,
        end: str | None,
    ) -> bool:
        """Check if this reader handles snapshot reads."""
        from ..models import ReaderType as RT

        # Handle SNAPSHOT reads or reads without start/end
        return read_type == RT.SNAPSHOT or (start is None or end is None)

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
        """Read snapshot values for all tags."""
        if not self.datasource:
            message = "Datasource is required for SNAPSHOT reads. "
            message += "Please set datasource when creating AspenClient."
            raise ValueError(message)

        logger.info(f"Reading {len(tags)} tag(s) snapshot values")

        builder = SqlSnapshotQueryBuilder()
        xml_query = builder.build(
            tags=tags,
            datasource=self.datasource,
            with_description=with_description,
        )

        sql_url = f"{self.base_url}/SQL"
        logger.debug(f"POST {sql_url}")
        logger.debug(f"Snapshot SQL query XML: {xml_query}")

        response = self._post_sql(xml_query)

        # Server local time, matching the timestamps of history reads
        snapshot_time = server_now(self.server_timezone)

        # IP.21 returns an empty body when none of the requested tags exist
        if not response.text or response.headers.get("content-length") == "0":
            logger.warning("Snapshot SQL endpoint returned empty response (unknown tags?)")
            return [], {}

        try:
            sql_response = response.json()
        except ValueError as e:
            message = f"Snapshot SQL endpoint returned non-JSON response: {response.text[:200]!r}"
            raise AspenSqlError(message) from e

        raise_for_sql_error(sql_response)

        snapshot_frame, snapshot_descriptions = self.parser.parse(
            sql_response,
            tags,
            include_status=include_status,
            snapshot_time=snapshot_time,
        )

        frames = []
        if not snapshot_frame.empty:
            frames.append(snapshot_frame)

        return frames, snapshot_descriptions
