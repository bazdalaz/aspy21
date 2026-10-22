"""Utility functions for the Aspen client."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, tzinfo
from itertools import islice
from typing import TypeVar

import numpy as np
import pandas as pd

T = TypeVar("T")


def chunked(iterable: Iterable[T], size: int) -> Iterable[list[T]]:
    """Split an iterable into chunks of specified size.

    Args:
        iterable: The input iterable to be chunked
        size: Maximum size of each chunk

    Yields:
        Lists of items, each containing up to 'size' elements
    """
    it = iter(iterable)
    while True:
        batch = list(islice(it, size))
        if not batch:
            return
        yield batch


# IP.21 interprets query timestamps as the server's local wall-clock time, and the REST API
# returns local wall-clock times labelled "Z" (UTC). These helpers keep everything in server
# local time; server_tz attaches the real zone when the caller knows it.


def check_timezone(server_tz: str | tzinfo | None) -> None:
    """Raise ValueError if server_tz is not a valid time zone."""
    if server_tz is None:
        return
    try:
        pd.Timestamp.now(tz=server_tz)
    except Exception as e:
        raise ValueError(f"Invalid server_timezone: {server_tz!r}") from e


def to_server_time(value: str | datetime, server_tz: str | tzinfo | None) -> pd.Timestamp:
    """Convert a timestamp to naive server-local wall-clock time.

    Naive values are taken as server local time already. Aware values are converted to
    server_tz, or to this machine's local zone when server_tz is None.

    Args:
        value: Timestamp string or datetime
        server_tz: Server time zone, or None to assume this machine's zone

    Returns:
        Naive pandas Timestamp in server local time
    """
    dt = pd.Timestamp(value)
    if not isinstance(dt, pd.Timestamp):
        raise ValueError(f"Invalid timestamp: {value!r}")
    if dt.tzinfo is None:
        return dt
    if server_tz is None:
        # This machine's UTC offset at that instant (DST-aware)
        server_tz = dt.to_pydatetime().astimezone().tzinfo
    return dt.tz_convert(server_tz).replace(tzinfo=None)


def server_now(server_tz: str | tzinfo | None) -> pd.Timestamp:
    """Return the current time as naive server-local wall-clock time."""
    if server_tz is None:
        return pd.Timestamp.now()
    return pd.Timestamp.now(tz=server_tz).tz_localize(None)


def localize_server_index(df: pd.DataFrame, server_tz: str | tzinfo | None) -> pd.DataFrame:
    """Set a DataFrame's time index to server local time.

    The "Z" the server attaches is dropped without shifting the wall-clock time. With
    server_tz, the index is then localized to that zone. Times repeated when clocks go
    back are inferred from order where possible, otherwise taken as standard time.

    Args:
        df: DataFrame with a DatetimeIndex parsed from server timestamps
        server_tz: Server time zone, or None to keep naive local times

    Returns:
        The DataFrame with its index adjusted
    """
    index = df.index
    if not isinstance(index, pd.DatetimeIndex):
        return df
    if index.tz is not None:
        index = index.tz_localize(None)
    if server_tz is not None:
        try:
            index = index.tz_localize(server_tz, ambiguous="infer", nonexistent="shift_forward")
        except Exception:
            # Inference fails e.g. for a single repeated time; the zone was validated by
            # check_timezone, so any other error is raised again by the call below
            index = index.tz_localize(
                server_tz, ambiguous=np.zeros(len(index), dtype=bool), nonexistent="shift_forward"
            )
    df = df.copy()
    df.index = index
    return df
