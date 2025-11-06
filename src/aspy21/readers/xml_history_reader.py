"""XML history reader for per-tag queries."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from ..query_builder import build_read_query
from .base_reader import BaseReader
from .response_parser import XmlHistoryResponseParser

if TYPE_CHECKING:
    from ..models import ReaderType

logger = logging.getLogger(__name__)


class XmlHistoryReader(BaseReader):
    """Reader for historical data using XML endpoint (loops over tags)."""

    def __init__(self, base_url: str, http_client, datasource: str | None = None):
        """Initialize XML history reader with response parser.

        Args:
            base_url: Base URL for the API
            http_client: HTTP client for making requests
            datasource: Optional datasource name
        """
        super().__init__(base_url, http_client, datasource)
        self.parser = XmlHistoryResponseParser()

    def can_handle(
        self,
        read_type: ReaderType,
        start: str | None,
        end: str | None,
    ) -> bool:
        """Check if this reader handles XML history reads."""
        # Fallback reader - handles all non-snapshot reads when SQL is not available
        return start is not None and end is not None

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
        """Read historical data for tags using XML endpoint (per-tag requests)."""
        logger.debug(f"Using XML endpoint for {read_type.value} read")
        logger.info(
            "Reading %d tag(s) from %s to %s (max_rows=%d)",
            len(tags),
            start,
            end,
            max_rows,
        )

        frames: list[pd.DataFrame] = []
        tag_descriptions: dict[str, str] = {}

        for tag_idx, tag in enumerate(tags, 1):
            logger.debug(f"Processing tag {tag_idx}/{len(tags)}: {tag}")

            assert start is not None
            assert end is not None

            xml_query = build_read_query(
                tag=tag,
                start=start,
                end=end,
                read_type=read_type,
                interval=interval,
                datasource=self.datasource,
                max_rows=max_rows,
                with_description=with_description,
            )

            response = self._fetch(xml_query)
            logger.debug(f"Received response for tag: {tag}")

            # Parse the Aspen-style response
            df, description = self.parser.parse(
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

        return frames, tag_descriptions

    @retry(wait=wait_exponential(multiplier=0.5, min=0.5, max=8), stop=stop_after_attempt(3))
    def _fetch(self, xml_query: str) -> dict:
        """Fetch data from API endpoint with automatic retry."""
        logger.debug(f"POST {self.base_url}")
        logger.debug(f"Query XML: {xml_query}")

        try:
            # Try sending XML as POST body with correct content type
            r = self.http_client.post(
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

        except Exception as e:
            import httpx

            if isinstance(e, httpx.HTTPStatusError):
                logger.error(f"HTTP {e.response.status_code} error for {self.base_url}")
                logger.error(f"Response body: {e.response.text[:500]}")
            elif isinstance(e, httpx.RequestError):
                logger.error(f"Request error: {type(e).__name__}: {e}")
            else:
                logger.error(f"Unexpected error: {type(e).__name__}: {e}")
            raise
