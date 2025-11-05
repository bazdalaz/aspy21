"""Snapshot reader for current values."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from ..query_builder import build_snapshot_sql_query
from .base_reader import BaseReader

if TYPE_CHECKING:
    from ..models import ReaderType

logger = logging.getLogger(__name__)


class SnapshotReader(BaseReader):
    """Reader for snapshot (current value) reads using SQL endpoint."""

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

        xml_query = build_snapshot_sql_query(
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

        snapshot_frame, snapshot_descriptions = self._parse_snapshot_sql_response(
            sql_response,
            tags,
            include_status=include_status,
            snapshot_time=snapshot_time,
        )

        frames = []
        if not snapshot_frame.empty:
            frames.append(snapshot_frame)

        return frames, snapshot_descriptions

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
