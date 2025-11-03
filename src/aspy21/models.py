"""Data models for Aspen InfoPlus.21 client."""

from enum import Enum


class ReaderType(str, Enum):
    """Reader types for Aspen IP.21 data retrieval.

    Attributes:
        RAW: Raw data points as stored in the historian
        INT: Interpolated values at specified intervals
        SNAPSHOT: Current snapshot of tag values
        AVG: Average values over specified intervals
    """

    RAW = "RAW"
    INT = "INT"
    SNAPSHOT = "SNAPSHOT"
    AVG = "AVG"
