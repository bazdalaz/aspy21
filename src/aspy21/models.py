"""Data models for Aspen InfoPlus.21 client."""

from enum import Enum


class ReaderType(str, Enum):
    """Reader types for Aspen IP.21 data retrieval.

    Attributes:
        RAW: Raw data points as stored in the historian
        INT: Interpolated values at specified intervals
        SNAPSHOT: Current snapshot of tag values
        AVG: Average values over specified intervals
        AGG_MIN: Minimum value over the period (from aggregates table)
        AGG_MAX: Maximum value over the period (from aggregates table)
        AGG_AVG: Average value over the period (from aggregates table)
        AGG_RNG: Range (max-min) over the period (from aggregates table)
    """

    RAW = "RAW"
    INT = "INT"
    SNAPSHOT = "SNAPSHOT"
    AVG = "AVG"
    AGG_MIN = "AGG_MIN"
    AGG_MAX = "AGG_MAX"
    AGG_AVG = "AGG_AVG"
    AGG_RNG = "AGG_RNG"


class IncludeFields(str, Enum):
    """Field inclusion options for read/search operations.

    Attributes:
        NONE: Include only timestamp and value
        STATUS: Include status field
        DESCRIPTION: Include description field
        ALL: Include both status and description fields
    """

    NONE = "NONE"
    STATUS = "STATUS"
    DESCRIPTION = "DESCRIPTION"
    ALL = "ALL"


class OutputFormat(str, Enum):
    """Output format options for read/search operations.

    Attributes:
        JSON: Return data as list of dictionaries
        DATAFRAME: Return data as pandas DataFrame
    """

    JSON = "JSON"
    DATAFRAME = "DATAFRAME"
