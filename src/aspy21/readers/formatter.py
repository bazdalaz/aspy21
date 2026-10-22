"""Data formatter for converting DataFrames to different output formats."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _merge_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Merge per-tag frames on their time index, keeping every row.

    Raw history can hold several values for one tag at the same timestamp. Each frame's
    rows are numbered within their timestamp, so the n-th value of one tag at a time is
    aligned with the n-th value of the others and no value is repeated or dropped.

    Args:
        frames: DataFrames indexed by time, one or more tags each

    Returns:
        A DataFrame sorted by time, with one row per timestamp and occurrence
    """
    numbered = []
    for frame in frames:
        occurrence = frame.groupby(level=0).cumcount().to_numpy()
        index = pd.MultiIndex.from_arrays(
            [frame.index, occurrence], names=[frame.index.name, "_occurrence"]
        )
        numbered.append(frame.set_axis(index, axis=0))

    merged = pd.concat(numbered, axis=1).sort_index()
    return merged.droplevel("_occurrence")


def _python_value(value: object) -> object:
    """Return a numpy scalar as the equivalent Python value (e.g. numpy.int64 -> int)."""
    return value.item() if isinstance(value, np.generic) else value


def _is_present(value: object) -> bool:
    """Return True for a scalar value that is not missing (NaN, None, NA, NaT)."""
    return pd.api.types.is_scalar(value) and not pd.isna(value)  # type: ignore[arg-type]


class OutputFormatter(ABC):
    """Abstract base class for output formatting strategies.

    Each formatter implements a specific strategy for formatting data
    (e.g., DataFrame, JSON) with various options (status, description).
    """

    def __init__(self, include_status: bool, with_description: bool):
        """Initialize formatter with configuration options.

        Args:
            include_status: Whether to include status information
            with_description: Whether to include tag descriptions
        """
        self.include_status = include_status
        self.with_description = with_description

    @abstractmethod
    def format(
        self,
        df: pd.DataFrame,
        tags: list[str],
        tag_descriptions: dict[str, str],
    ) -> pd.DataFrame | list[dict]:
        """Format the merged DataFrame into the desired output format.

        Args:
            df: Merged DataFrame with all tag data
            tags: List of requested tag names
            tag_descriptions: Dictionary of tag descriptions

        Returns:
            Formatted output (DataFrame or list of dictionaries)
        """


class DataFrameFormatter(OutputFormatter):
    """Formatter strategy for DataFrame output.

    Handles column ordering, description columns, and metadata preservation.
    """

    def format(
        self,
        df: pd.DataFrame,
        tags: list[str],
        tag_descriptions: dict[str, str],
    ) -> pd.DataFrame:
        """Format merged DataFrame with proper column ordering and descriptions.

        Args:
            df: Merged DataFrame with all tag data
            tags: List of requested tag names
            tag_descriptions: Dictionary of tag descriptions

        Returns:
            Formatted DataFrame
        """
        if df.empty:
            return df

        out = df.copy()

        # Add description columns if requested
        if self.with_description:
            for tag in tags:
                if tag in out.columns:
                    desc_col = f"{tag}_description"
                    description_value = tag_descriptions.get(tag)
                    if description_value:
                        out[desc_col] = description_value
                    else:
                        out[desc_col] = pd.NA
            # Preserve metadata
            out.attrs["tag_descriptions"] = tag_descriptions

        # Reorder columns: tag -> description -> status (for each tag in order)
        if self.include_status or self.with_description:
            ordered_cols: list[str] = []
            for tag in tags:
                if tag in out.columns:
                    ordered_cols.append(tag)
                    if self.with_description:
                        desc_col = f"{tag}_description"
                        if desc_col in out.columns:
                            ordered_cols.append(desc_col)
                    if self.include_status:
                        status_col = f"{tag}_status"
                        if status_col in out.columns:
                            ordered_cols.append(status_col)

            # Add any remaining columns not explicitly ordered
            remaining_cols = [col for col in out.columns if col not in ordered_cols]
            if ordered_cols:
                out = out.loc[:, ordered_cols + remaining_cols]

        return out


class JsonFormatter(OutputFormatter):
    """Formatter strategy for JSON list output.

    Converts DataFrame to list of dictionaries with one record per tag per timestamp.
    """

    def format(
        self,
        df: pd.DataFrame,
        tags: list[str],
        tag_descriptions: dict[str, str],
    ) -> list[dict]:
        """Convert DataFrame to JSON list format.

        Args:
            df: Merged DataFrame with all tag data
            tags: List of requested tag names
            tag_descriptions: Dictionary of tag descriptions

        Returns:
            List of dictionaries with timestamp, tag, value, and optional fields
        """
        json_data: list[dict] = []

        # Read values column by column: iterrows() casts each row to one dtype, which
        # turns integers into floats when a row also holds a float column
        tags = [tag for tag in tags if tag in df.columns]
        values = {tag: df[tag].tolist() for tag in tags}
        statuses = {}
        if self.include_status:
            statuses = {
                tag: df[f"{tag}_status"].tolist() for tag in tags if f"{tag}_status" in df.columns
            }

        for position, idx in enumerate(df.index):
            # idx is pandas Timestamp, which has isoformat method
            ts = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)

            for tag in tags:
                value = values[tag][position]
                if not _is_present(value):
                    continue

                record: dict[str, object] = {
                    "timestamp": ts,
                    "tag": tag,
                    "value": _python_value(value),
                }

                # Add optional fields based on configuration
                if self.with_description:
                    record["description"] = tag_descriptions.get(tag, "")

                if tag in statuses:
                    status_value = statuses[tag][position]
                    if _is_present(status_value):
                        record["status"] = _python_value(status_value)

                json_data.append(record)

        logger.debug(f"Converted to {len(json_data)} JSON records")
        return json_data


class DataFormatter:
    """Formats reader output into final user-facing format.

    Acts as a context that selects and uses the appropriate formatting strategy
    based on the desired output format (DataFrame or JSON).
    """

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
        # Handle empty frames case
        if not frames:
            logger.warning("No data returned from API")
            if not as_df:
                return []
            return pd.DataFrame()

        # Common preprocessing: merge frames and sort by time index
        merged_df = _merge_frames(frames)

        # Select appropriate formatting strategy
        formatter: OutputFormatter
        if as_df:
            formatter = DataFrameFormatter(
                include_status=include_status,
                with_description=with_description,
            )
        else:
            formatter = JsonFormatter(
                include_status=include_status,
                with_description=with_description,
            )

        # Use the selected strategy to format the output
        result = formatter.format(merged_df, tags, tag_descriptions)

        # Log success information
        if as_df and isinstance(result, pd.DataFrame):
            logger.info(
                f"Successfully retrieved {len(result)} rows for {len(result.columns)} column(s)"
            )
        elif isinstance(result, list):
            logger.info(f"Successfully retrieved {len(result)} JSON records")

        return result
