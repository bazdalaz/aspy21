"""Data formatter for converting DataFrames to different output formats."""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


class DataFormatter:
    """Formats reader output into final user-facing format."""

    @staticmethod
    def format_output(
        frames: list[pd.DataFrame],
        tags: list[str],
        tag_descriptions: dict[str, str],
        as_df: bool,
        include_status: bool,
        with_description: bool,
    ) -> pd.DataFrame | list[dict]:
        """Format frames into final output (DataFrame or JSON list).

        Args:
            frames: List of DataFrames from readers
            tags: List of requested tag names
            tag_descriptions: Dictionary of tag descriptions
            as_df: Return as DataFrame if True, JSON list if False
            include_status: Whether status columns are included
            with_description: Whether descriptions should be included

        Returns:
            Formatted output as DataFrame or list of dictionaries
        """
        if not frames:
            logger.warning("No data returned from API")
            if not as_df:
                return []
            return pd.DataFrame()

        # Merge frames by index (time), combining columns for different tags
        out = pd.concat(frames, axis=1)
        out = out.sort_index()

        if with_description and as_df:
            # Attach descriptions as dedicated columns and preserve metadata.
            for tag in tags:
                if tag in out.columns:
                    desc_col = f"{tag}_description"
                    description_value = tag_descriptions.get(tag)
                    if description_value:
                        out[desc_col] = description_value
                    else:
                        out[desc_col] = pd.NA
            out.attrs["tag_descriptions"] = tag_descriptions

        if include_status or (with_description and as_df):
            ordered_cols: list[str] = []
            for tag in tags:
                if tag in out.columns:
                    ordered_cols.append(tag)
                    if with_description and as_df:
                        desc_col = f"{tag}_description"
                        if desc_col in out.columns:
                            ordered_cols.append(desc_col)
                    if include_status:
                        status_col = f"{tag}_status"
                        if status_col in out.columns:
                            ordered_cols.append(status_col)
            remaining_cols = [col for col in out.columns if col not in ordered_cols]
            if ordered_cols:
                out = out.loc[:, ordered_cols + remaining_cols]

        logger.info(f"Successfully retrieved {len(out)} rows for {len(out.columns)} column(s)")

        # Convert to JSON format if requested
        if not as_df:
            return DataFormatter._to_json(
                out, tags, tag_descriptions, include_status, with_description
            )

        return out

    @staticmethod
    def _to_json(
        df: pd.DataFrame,
        tags: list[str],
        tag_descriptions: dict[str, str],
        include_status: bool,
        with_description: bool,
    ) -> list[dict]:
        """Convert DataFrame to JSON format."""
        json_data: list[dict] = []
        for idx, row in df.iterrows():
            # Iterate through each tag (column) in this row
            for tag in tags:
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
                            "value": value,
                        }
                        if with_description:
                            record["description"] = tag_descriptions.get(tag, "")
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
