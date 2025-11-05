"""XML history reader for per-tag queries."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from ..query_builder import build_read_query
from .base_reader import BaseReader

if TYPE_CHECKING:
    from ..models import ReaderType

logger = logging.getLogger(__name__)


class XmlHistoryReader(BaseReader):
    """Reader for historical data using XML endpoint (loops over tags)."""

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

    def _parse_aspen_response(
        self, response: dict, tag_name: str, include_status: bool, max_rows: int
    ) -> tuple[pd.DataFrame, str]:
        """Parse Aspen REST API response into DataFrame."""
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
