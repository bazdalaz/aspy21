"""Snapshot reader for current values."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from ..query_builder import SqlSnapshotQueryBuilder
from .base_reader import BaseReader
from .response_parser import SqlSnapshotResponseParser

if TYPE_CHECKING:
    import httpx

    from ..models import ReaderType

logger = logging.getLogger(__name__)


class SnapshotReader(BaseReader):
    """Reader for snapshot (current value) reads using SQL endpoint."""

    def __init__(self, base_url: str, datasource: str, http_client: httpx.Client):
        """Initialize snapshot reader with response parser.

        Args:
            base_url: Base URL for the API
            datasource: Datasource name
            http_client: HTTP client for making requests
        """
        super().__init__(base_url, datasource, http_client)
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

        response = self.http_client.post(
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
