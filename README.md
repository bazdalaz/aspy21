
# Aspy21

**Python Client for Aspen InfoPlus.21 (IP.21)**

[![PyPI version](https://img.shields.io/pypi/v/aspy21.svg)](https://pypi.org/project/aspy21/)
[![Python versions](https://img.shields.io/pypi/pyversions/aspy21.svg)](https://pypi.org/project/aspy21/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/bazdalaz/aspy21/blob/main/LICENSE)
[![Tests](https://github.com/bazdalaz/aspy21/actions/workflows/tests.yml/badge.svg)](https://github.com/bazdalaz/aspy21/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/bazdalaz/aspy21/branch/main/graph/badge.svg)](https://codecov.io/gh/bazdalaz/aspy21)

> **Note**: This is an independent, unofficial client library. Not affiliated with AspenTech.

---

## Overview

**aspy21** is a modern, high-performance Python client for Aspen InfoPlus.21 (IP.21) built on the AspenOne ProcessData REST API. It provides unified access to process historian data with pandas DataFrame output, automatic batching, and optional caching.

### Key Capabilities

- REST-based communication with Aspen IP.21 historian
- Basic HTTP authentication (cross-platform compatible)
- **Hybrid search mode**: Search for tags and read their data in one call
- Tag search with wildcards and description filtering
- Unified interface for analog, discrete, and text tags
- Support for RAW, INT, SNAPSHOT, and aggregate reader types (AVG, MIN, MAX, RNG)
- **Smart aggregates**: Query aggregates table with or without intervals for flexible period-based statistics
- Pandas DataFrame or JSON output with optional status and description fields
- Enum-based parameters for cleaner, type-safe API
- Configurable row limits and query parameters
- Automatic retries of transient failures (connection errors, HTTP 429/502/503/504)
- Fully type-annotated: editors and type checkers know whether a call returns a
  DataFrame, a list of records or a list of tag names

### Use Cases

- Industrial data analysis and reporting
- Integration with data analytics pipelines
- Process monitoring and dashboard development
- Time-series data extraction and transformation

---

## Installation

Install via pip:

```bash
pip install aspy21
```

### Requirements

- Python 3.9+
- httpx >= 0.27
- pandas >= 2.0
- tenacity >= 9.0

---

## Quick Start

### Basic Usage with Context Manager

```python
from aspy21 import AspenClient, OutputFormat, ReaderType

# Initialize client using context manager (recommended)
with AspenClient(
    base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
    auth=("user", "password"),
    datasource="IP21",  # Required for reads and searches
) as client:
    # Read historical data
    df = client.read(
        ["TEMP_201", "PRESS_201.PV"],
        start="2025-06-20 08:00:00",
        end="2025-06-20 09:00:00",
        read_type=ReaderType.RAW,
        output=OutputFormat.DATAFRAME,
    )

    print(df)
    # Connection automatically closed
```

`base_url` is the address of the ProcessData REST API, including `AtProcessDataREST.dll`:
`http://<server>/ProcessData/AtProcessDataREST.dll`. `datasource` is the IP.21 data
source name; reads and searches raise `ValueError` without it.

---

## Usage Examples

### Reading Aggregates Data

The aggregates reader types (AVG, MIN, MAX, RNG) query the IP.21 aggregates table for period-based statistics.

#### Average Values Over Time Intervals

```python
from aspy21 import AspenClient, ReaderType, OutputFormat

with AspenClient(
    base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
    auth=("user", "password"),
    datasource="IP21"
) as client:
    # Get 10-minute averages for a 1-hour period
    df = client.read(
        ["REACTOR_TEMP", "REACTOR_PRESSURE"],
        start="2025-01-15 08:00:00",
        end="2025-01-15 09:00:00",
        interval=600,  # 10 minutes (600 seconds)
        read_type=ReaderType.AVG,
        output=OutputFormat.DATAFRAME
    )
    # Returns 6 rows (one average per 10-minute interval)
    print(df)
```

#### Single Aggregate Value for Entire Period

```python
# Get a single average value over 24 hours (no interval)
with AspenClient(
    base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
    auth=("user", "password"),
    datasource="IP21"
) as client:
    data = client.read(
        ["REACTOR_TEMP"],
        start="2025-01-15 00:00:00",
        end="2025-01-16 00:00:00",
        read_type=ReaderType.AVG,  # No interval specified
        output=OutputFormat.JSON
    )
    # Returns: [{"timestamp": "...", "tag": "REACTOR_TEMP", "value": 285.4}]
    print(f"24-hour average: {data[0]['value']}")
```

#### Minimum and Maximum Values

```python
# Find daily min/max temperatures
with AspenClient(
    base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
    auth=("user", "password"),
    datasource="IP21"
) as client:
    # Minimum values per hour
    min_df = client.read(
        ["REACTOR_TEMP"],
        start="2025-01-15 00:00:00",
        end="2025-01-16 00:00:00",
        interval=3600,  # 1 hour
        read_type=ReaderType.MIN,
        output=OutputFormat.DATAFRAME
    )

    # Maximum values per hour
    max_df = client.read(
        ["REACTOR_TEMP"],
        start="2025-01-15 00:00:00",
        end="2025-01-16 00:00:00",
        interval=3600,
        read_type=ReaderType.MAX,
        output=OutputFormat.DATAFRAME
    )

    print(f"Hourly minimums:\n{min_df}")
    print(f"Hourly maximums:\n{max_df}")
```

#### Range (Max - Min) Values

```python
# Calculate hourly temperature ranges (variability)
with AspenClient(
    base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
    auth=("user", "password"),
    datasource="IP21"
) as client:
    df = client.read(
        ["REACTOR_TEMP", "COLUMN_TEMP"],
        start="2025-01-15 00:00:00",
        end="2025-01-15 12:00:00",
        interval=3600,  # 1 hour
        read_type=ReaderType.RNG,  # Range = Max - Min
        output=OutputFormat.DATAFRAME
    )
    # Shows temperature variability over each hour
    print(df)
```

#### Combining Multiple Aggregate Types

```python
# Get comprehensive statistics for a process variable
with AspenClient(
    base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
    auth=("user", "password"),
    datasource="IP21"
) as client:
    tag = "REACTOR_TEMP"
    period_start = "2025-01-15 08:00:00"
    period_end = "2025-01-15 16:00:00"

    # Get all statistics for 1-hour intervals
    avg = client.read([tag], start=period_start, end=period_end,
                      interval=3600, read_type=ReaderType.AVG)
    min_vals = client.read([tag], start=period_start, end=period_end,
                           interval=3600, read_type=ReaderType.MIN)
    max_vals = client.read([tag], start=period_start, end=period_end,
                           interval=3600, read_type=ReaderType.MAX)
    rng = client.read([tag], start=period_start, end=period_end,
                      interval=3600, read_type=ReaderType.RNG)

    # Combine into analysis
    import pandas as pd
    stats = pd.DataFrame({
        'avg': [d['value'] for d in avg],
        'min': [d['value'] for d in min_vals],
        'max': [d['value'] for d in max_vals],
        'range': [d['value'] for d in rng],
    })
    print(stats)
```

### Reading Raw and Interpolated Data

```python
# Raw historical data (as stored in historian)
with AspenClient(
    base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
    auth=("user", "password"),
    datasource="IP21"
) as client:
    raw_df = client.read(
        ["FLOW_101", "LEVEL_205"],
        start="2025-01-15 08:00:00",
        end="2025-01-15 09:00:00",
        read_type=ReaderType.RAW,
        output=OutputFormat.DATAFRAME
    )
    print(f"Raw data points: {len(raw_df)}")

    # Interpolated data at regular intervals
    int_df = client.read(
        ["FLOW_101", "LEVEL_205"],
        start="2025-01-15 08:00:00",
        end="2025-01-15 09:00:00",
        interval=60,  # 1-minute intervals
        read_type=ReaderType.INT,
        output=OutputFormat.DATAFRAME
    )
    print(f"Interpolated data points: {len(int_df)}")
```

### Reading Several Tags

Values of all tags are merged on one time index, sorted by time. A tag that has no value
at a timestamp is `NaN` there in a DataFrame, and has no record in JSON output:

```python
df = client.read(
    ["FLOW_101", "LEVEL_205"],
    start="2025-01-15 08:00:00",
    end="2025-01-15 09:00:00",
    read_type=ReaderType.RAW,
    include=IncludeFields.STATUS,
    output=OutputFormat.DATAFRAME,
)
#                      FLOW_101  FLOW_101_status  LEVEL_205  LEVEL_205_status
# time
# 2025-01-15 08:00:00      12.5              0.0        NaN               NaN
# 2025-01-15 08:00:30       NaN              NaN       40.1               0.0
# 2025-01-15 08:01:00      12.7              0.0       40.3               0.0
```

- Status and description columns are named `<tag>_status` and `<tag>_description` and
  follow their tag's column
- Raw history can hold several values of one tag at the same timestamp. Each is kept on
  its own row, so the index of a RAW read can contain a timestamp more than once
- Tags that returned no data have no column (DataFrame) or no records (JSON)
- `limit` applies to each tag. All tags are read in one query; if a tag has more than
  `limit` values in the range, the tags that query cut short are read again one at a time,
  so each tag gets up to `limit` values. Reads below the limit take a single query
- JSON values are plain Python `int`, `float` or `str`. In a DataFrame, a tag column with
  gaps holds floats, since pandas needs a float column to hold `NaN`

### Snapshot (Current Values)

```python
# Get current values for multiple tags
with AspenClient(
    base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
    auth=("user", "password"),
    datasource="IP21"
) as client:
    # Method 1: Explicit SNAPSHOT read type
    df = client.read(
        ["TEMP_101", "PRESSURE_102", "FLOW_103"],
        read_type=ReaderType.SNAPSHOT,
        output=OutputFormat.DATAFRAME
    )

    # Method 2: Omit start/end (defaults to SNAPSHOT)
    df = client.read(
        ["TEMP_101", "PRESSURE_102", "FLOW_103"],
        output=OutputFormat.DATAFRAME
    )

    print(df)
```

### Search and Read (Hybrid Mode)

```python
# Search for tags and read their data in one call
with AspenClient(
    base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
    auth=("user", "password"),
    datasource="IP21"
) as client:
    # Find all reactor temperature tags and get hourly averages
    df = client.search(
        tag="REACTOR_*_TEMP",
        start="2025-01-15 00:00:00",
        end="2025-01-16 00:00:00",
        interval=3600,
        read_type=ReaderType.AVG,
        output=OutputFormat.DATAFRAME
    )
    print(f"Found and read data for {len(df.columns)} tags")
    print(df)
```

### Including Status and Descriptions

```python
from aspy21 import IncludeFields

with AspenClient(
    base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
    auth=("user", "password"),
    datasource="IP21"
) as client:
    # Include quality status codes
    df = client.read(
        ["REACTOR_TEMP"],
        start="2025-01-15 08:00:00",
        end="2025-01-15 09:00:00",
        interval=600,
        read_type=ReaderType.AVG,
        include=IncludeFields.STATUS,
        output=OutputFormat.DATAFRAME
    )
    # DataFrame includes REACTOR_TEMP and REACTOR_TEMP_status columns

    # Include descriptions
    df = client.read(
        ["REACTOR_TEMP"],
        start="2025-01-15 08:00:00",
        end="2025-01-15 09:00:00",
        interval=600,
        read_type=ReaderType.AVG,
        include=IncludeFields.DESCRIPTION,
        output=OutputFormat.DATAFRAME
    )

    # Include both status and descriptions
    df = client.read(
        ["REACTOR_TEMP"],
        start="2025-01-15 08:00:00",
        end="2025-01-15 09:00:00",
        interval=600,
        read_type=ReaderType.AVG,
        include=IncludeFields.ALL,
        output=OutputFormat.DATAFRAME
    )
```

---

## Authentication

### HTTP Basic Authentication

```python
with AspenClient(
    base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
    auth=("user", "password"),
    datasource="IP21"  # Required for historical reads
) as client:
    # Your code here
    pass
```

### No Authentication

For public or internal endpoints:

```python
with AspenClient(
    base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
    datasource="IP21"  # Required for historical reads
) as client:
    # Your code here
    pass
```

---

## Caching

### Overview

An optional in-memory cache returns repeated reads of past data without a server
round trip. It uses TTL (Time-To-Live) expiry with eviction of the oldest entries, and is
thread-safe. It is off by default.

### What Is Cached

- **Historical reads** (RAW, INT) whose end time is more than a minute in the past:
  24 hours (`ttl_historical`) - this data doesn't change
- **Aggregate reads** (AVG, MIN, MAX, RNG) of past periods: 24 hours (`ttl_aggregates`)
- **Search results**: 1 hour (`ttl_search`) - tag lists change infrequently
- **Not cached**: snapshot reads, reads ending in the last minute or in the future, empty
  results, and failed requests

### Enabling Cache

#### Basic Usage (Default Configuration)

```python
from aspy21 import AspenClient

# Enable caching with defaults
with AspenClient(
    base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
    auth=("user", "password"),
    datasource="IP21",
    cache=True,  # Enable with default settings
) as client:
    # First read hits API
    data1 = client.read(["TAG1"], start="2025-01-01 08:00:00", end="2025-01-01 09:00:00")

    # Second identical read hits cache (10-100x faster!)
    data2 = client.read(["TAG1"], start="2025-01-01 08:00:00", end="2025-01-01 09:00:00")

    # Check cache statistics
    stats = client.get_cache_stats()
    print(f"Cache hit rate: {stats['hit_rate_percent']}%")
```

#### Custom Configuration

```python
from aspy21 import AspenClient, CacheConfig

# Configure cache with custom TTLs and size
config = CacheConfig(
    enabled=True,
    max_size=500,           # Limit to 500 cached entries
    ttl_historical=7200,    # 2 hours for RAW and INT reads
    ttl_search=1800,        # 30 minutes for search results
    ttl_aggregates=7200,    # 2 hours for aggregates
)

with AspenClient(
    base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
    auth=("user", "password"),
    datasource="IP21",
    cache=config,  # Use custom configuration
) as client:
    # Your code here
    pass
```

#### Share Cache Across Clients

```python
from aspy21 import AspenClient, AspenCache

# Create a shared cache instance
shared_cache = AspenCache()

# Use same cache for multiple clients
with AspenClient(base_url=url1, datasource="IP21", cache=shared_cache) as client1:
    with AspenClient(base_url=url2, datasource="IP21", cache=shared_cache) as client2:
        # Both clients share the same cache; their entries are kept apart by server and
        # datasource
        client1.read([...])
        client2.read([...])

        # Combined statistics
        stats = shared_cache.get_stats()
```

### Cache Management

#### Get Statistics

```python
stats = client.get_cache_stats()
print(f"Cache size: {stats['size']} entries")
print(f"Hit rate: {stats['hit_rate_percent']}%")
print(f"Hits: {stats['hits']}, Misses: {stats['misses']}")
```

#### Clear Cache

```python
# Clear all cached entries
count = client.clear_cache()
print(f"Cleared {count} entries")
```

#### Invalidate Specific Entries

```python
# Invalidate cached reads for specific tags/time range
count = client.invalidate_cache(
    tags=["TAG1", "TAG2"],
    start="2025-01-01 00:00:00",
    end="2025-01-01 01:00:00"
)

# Any argument can be omitted: this removes every cached read that includes TAG1
count = client.invalidate_cache(tags=["TAG1"])
```

A cached read is removed when it includes any of the given tags and its start and end
match. Only reads from this client's server and datasource are affected; search results
are kept.

### Performance

A cache hit skips the request to IP.21, so it takes milliseconds however long the query
took on the server. How much load it saves depends on how often the same reads repeat.

**Example Timing:**
```python
import time

with AspenClient(base_url=url, auth=auth, datasource="IP21", cache=True) as client:
    # First call - hits API
    start = time.time()
    df1 = client.read(["TAG1"], start="2025-01-01 08:00:00", end="2025-01-01 09:00:00")
    api_time = time.time() - start
    print(f"API call: {api_time:.3f}s")

    # Second call - from cache
    start = time.time()
    df2 = client.read(["TAG1"], start="2025-01-01 08:00:00", end="2025-01-01 09:00:00")
    cache_time = time.time() - start
    print(f"Cache hit: {cache_time:.3f}s")
```

### Cache Behavior Details

**Cache Keys:**
- A cached result is only returned for a request with the same tags (in the same order),
  time range, interval, read type, fields, limit and output format, from the same server,
  datasource and `server_timezone`
- Results are copied in and out of the cache, so changing a returned DataFrame or list
  does not change later cache hits

**Thread Safety:**
- All cache operations are thread-safe
- Can be safely used in multi-threaded applications

**Memory Management:**
- The oldest entry is evicted when `max_size` is reached
- Automatic cleanup of expired entries
- Configurable size limits prevent memory issues

---

## API Reference

### AspenClient

**Constructor Parameters** (all except `base_url` are keyword-only):

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `base_url` | str | required | URL of the ProcessData REST API, ending in `AtProcessDataREST.dll` |
| `auth` | Auth\|tuple\|None | None | Authentication as (username, password) tuple or httpx Auth object |
| `timeout` | float | 30.0 | Request timeout in seconds |
| `verify_ssl` | bool | True | Whether to verify SSL certificates |
| `datasource` | str\|None | None | IP.21 datasource name. Required: reads and searches raise `ValueError` without it |
| `http_client` | httpx.Client\|None | None | Use this HTTP client instead of creating one. `auth`, `timeout` and `verify_ssl` are not applied to it |
| `cache` | AspenCache\|CacheConfig\|bool\|None | None | Enable caching: True (default config), CacheConfig instance, or AspenCache instance |
| `server_timezone` | str\|tzinfo\|None | None | Time zone of the IP.21 server, e.g. `"Europe/Berlin"`. See [Timestamps and Time Zones](#timestamps-and-time-zones) |
| `retries` | int | 2 | How many times to repeat a request after a transient failure; 0 disables retries. See [Retries](#retries) |

### read() Method

Read historical or snapshot data for multiple tags.

**Signature**:
```python
def read(
    tags: list[str],
    *,
    start: str | None = None,
    end: str | None = None,
    interval: int | None = None,
    read_type: ReaderType = ReaderType.INT,
    include: IncludeFields = IncludeFields.NONE,
    limit: int = 100_000,
    output: OutputFormat = OutputFormat.JSON,
) -> pd.DataFrame | list[dict]: ...
```

Type checkers and editors infer the exact type from `output`: `pd.DataFrame` for
`OutputFormat.DATAFRAME`, `list[dict]` for `OutputFormat.JSON` (the default).

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tags` | list[str] | required | List of tag names to retrieve. Case does not matter (`tag1.pv` reads `TAG1.PV`); results use the names as given |
| `start` | str\|None | None | Start timestamp (ISO format). With neither `start` nor `end`, current values are read (SNAPSHOT) |
| `end` | str\|None | None | End timestamp (ISO format). Defaults to the current time when only `start` is given |
| `interval` | int\|None | None | Seconds between interpolated values (INT), or the length of each aggregate period (AVG, MIN, MAX, RNG) |
| `read_type` | ReaderType | INT | Data retrieval mode (RAW, INT, SNAPSHOT, AVG, MIN, MAX, RNG) |
| `include` | IncludeFields | NONE | Which optional fields to include (NONE, STATUS, DESCRIPTION, ALL) |
| `limit` | int | 100000 | Maximum rows to return per tag. A tag that reaches it logs a warning, since later values in the range are not read |
| `output` | OutputFormat | JSON | Output format (JSON or DATAFRAME) |

**Returns**:
- If `output=OutputFormat.DATAFRAME`: pandas.DataFrame with time index and columns for each tag. See [Reading Several Tags](#reading-several-tags).
- If `output=OutputFormat.JSON`: List of dictionaries with `timestamp`, `tag`, `value`, and optional `description`/`status` fields.

**Raises**: `ValueError` (no tags, or no `datasource`), `AspenSqlError` (IP.21 rejected the
query), `httpx.HTTPStatusError` and `httpx.RequestError` (after any retries). See
[Error Handling](#error-handling).

**Examples**:
```python
# JSON output (default)
data = client.read(
    ["TEMP_201"],
    start="2025-01-01 00:00:00",
    end="2025-01-01 01:00:00"
)

# DataFrame output with status and descriptions
df = client.read(
    ["TEMP_201", "PRESS_201.PV"],
    start="2025-01-01 00:00:00",
    end="2025-01-01 01:00:00",
    output=OutputFormat.DATAFRAME,
    include=IncludeFields.ALL
)
```

> **Snapshot reads:**
> - Supplying no `start`/`end` (or explicitly choosing `ReaderType.SNAPSHOT`) returns the latest values.
> - When `include=IncludeFields.STATUS` or `IncludeFields.ALL`, includes quality/status codes.

### search() Method

Search for tags by name pattern and/or description. Optionally read their data in hybrid mode.

**Signature**:
```python
def search(
    tag: str = "*",
    *,
    description: str | None = None,
    case_sensitive: bool = False,
    limit: int = 10_000,
    # Optional read parameters for hybrid mode
    start: str | None = None,
    end: str | None = None,
    interval: int | None = None,
    read_type: ReaderType = ReaderType.INT,
    include: IncludeFields = IncludeFields.NONE,
    output: OutputFormat = OutputFormat.JSON,
) -> pd.DataFrame | list[dict] | list[str]: ...
```

Type checkers and editors infer the exact type:
- Search without `start`: `list[str]`, or `list[dict]` with `include=IncludeFields.DESCRIPTION`
  or `ALL`
- Hybrid mode (with `start`): `pd.DataFrame` for `output=OutputFormat.DATAFRAME`, otherwise
  `list[dict]`

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tag` | str | `"*"` | Tag name pattern with wildcards (`*`, `?`) |
| `description` | str\|None | None | Description filter (case-insensitive). Uses SQL endpoint when provided. |
| `case_sensitive` | bool | False | Case-sensitive tag matching (Browse endpoint only) |
| `limit` | int | 10000 | Max results (search mode) or max rows per tag (hybrid mode) |
| `start` | str\|None | None | **Triggers hybrid mode**: Start timestamp for data retrieval |
| `end` | str\|None | None | End timestamp (defaults to current time if omitted) |
| `interval` | int\|None | None | Interval in seconds for aggregated data |
| `read_type` | ReaderType | INT | Data retrieval mode for hybrid mode |
| `include` | IncludeFields | NONE | Search-only: DESCRIPTION or ALL adds descriptions. Hybrid: fields added to the data |
| `output` | OutputFormat | JSON | Output format in hybrid mode (JSON or DATAFRAME) |

**Returns**:
- **Search-only mode** (no `start`):
  - If `include=NONE` or `STATUS`: List of tag name strings
  - If `include=DESCRIPTION` or `ALL`: List of dicts with 'name' and 'description'
- **Hybrid mode** (with `start`):
  - If `output=JSON`: List of dicts with timestamp, tag, value, and optional fields
  - If `output=DATAFRAME`: pandas DataFrame

**Requirements**:
- `datasource` must be configured in AspenClient

**Modes**:
1. **Search-only** (no `start`): Find tags matching criteria
2. **Hybrid mode** (with `start`): Search for tags AND read their data in one call

**Wildcards**:
- `*` - Matches any number of characters
- `?` - Matches exactly one character

**Examples**:
```python
# Search-only: Get tag names (default)
tag_names = client.search("TEMP*")
# Returns: ["TEMP_101", "TEMP_102", ...]

# Search-only: Get tags with descriptions
tags = client.search("TEMP*", include=IncludeFields.DESCRIPTION)
# Returns: [{"name": "TEMP_101", "description": "Reactor temp"}, ...]

# Hybrid mode: Search and read data in one call
df = client.search(
    "TEMP*",
    start="2025-01-01 00:00:00",
    end="2025-01-01 01:00:00",
    output=OutputFormat.DATAFRAME
)
# Returns: DataFrame with data for all TEMP* tags

# Search by description (SQL endpoint)
tags = client.search(description="reactor", include=IncludeFields.DESCRIPTION)

# Combine pattern and description
tags = client.search("AI_1*", description="pressure", include=IncludeFields.DESCRIPTION)
```

### Enums

#### ReaderType

Data retrieval modes:

- `ReaderType.RAW` - Raw data points as stored in historian
- `ReaderType.INT` - Interpolated values, `interval` seconds apart (default)
- `ReaderType.SNAPSHOT` - Current snapshot of tag values
- `ReaderType.AVG` - Average values from aggregates table (with/without interval)
- `ReaderType.MIN` - Minimum value over the period (from aggregates table)
- `ReaderType.MAX` - Maximum value over the period (from aggregates table)
- `ReaderType.RNG` - Range (max-min) over the period (from aggregates table)

**Aggregates types** (AVG, MIN, MAX, RNG) query the `aggregates` table with the period automatically calculated in tenths of seconds:
- **Without interval**: `period = (end - start) * 10` → returns 1 aggregate value for entire range
- **With interval**: `period = interval * 10` → returns multiple values (one per interval period)

Example: A 24-hour period becomes `864000` tenths of seconds (24 × 60 × 60 × 10), while a 10-minute interval becomes `6000` (600 × 10).

#### IncludeFields

Controls which optional fields to include in responses:

- `IncludeFields.NONE` - Include only timestamp and value (default)
- `IncludeFields.STATUS` - Include status/quality codes
- `IncludeFields.DESCRIPTION` - Include tag descriptions
- `IncludeFields.ALL` - Include both status and description

#### OutputFormat

Controls output format:

- `OutputFormat.JSON` - Return as list of dictionaries (default)
- `OutputFormat.DATAFRAME` - Return as pandas DataFrame

**Examples**:
```python
from aspy21 import AspenClient, IncludeFields, OutputFormat, ReaderType

# AVG with interval: returns multiple average values (one per interval)
df = client.read(
    ["TAG1", "TAG2"],
    start="2025-01-01 00:00:00",
    end="2025-01-01 01:00:00",
    read_type=ReaderType.AVG,
    interval=600,  # 10-minute averages - returns 6 values (60min / 10min)
    include=IncludeFields.ALL,
    output=OutputFormat.DATAFRAME
)

# AVG without interval: returns single aggregate value for entire period
avg_value = client.read(
    ["TAG1"],
    start="2025-01-01 00:00:00",
    end="2025-01-02 00:00:00",
    read_type=ReaderType.AVG,  # Single average over 24 hours
    output=OutputFormat.JSON
)
# Returns: [{"timestamp": "...", "tag": "TAG1", "value": 42.5}]

# Other aggregates (MIN/MAX/RNG) work the same way
min_value = client.read(
    ["TAG1"],
    start="2025-01-01 00:00:00",
    end="2025-01-02 00:00:00",
    read_type=ReaderType.MIN,  # Minimum value over 24 hours
    output=OutputFormat.JSON
)
```

---

## Configuration

### Connection Settings

```python
with AspenClient(
    base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
    auth=("user", "password"),
    timeout=60.0,           # Request timeout (seconds)
    verify_ssl=True,        # SSL certificate verification
    datasource="IP21"       # Required for search operations
) as client:
    # Your code here
    pass
```

### Timestamps and Time Zones

IP.21 interprets query timestamps in the server's local time and returns server local
times (the REST API labels them `Z`, but they are not UTC). aspy21 therefore works in
server local time:

- **Default (`server_timezone=None`)**: returned timestamps are naive server-local times.
  Naive `start`/`end` values are sent as they are; timezone-aware values are converted
  to this machine's local zone first.
- **`server_timezone="Europe/Berlin"`**: returned timestamps are timezone-aware in that
  zone, and timezone-aware `start`/`end` values are converted to it.
- For a server that really returns UTC, use `server_timezone="UTC"`.

```python
with AspenClient(
    base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
    auth=("user", "password"),
    datasource="IP21",
    server_timezone="Europe/Berlin",
) as client:
    data = client.read(["TEMP_201"], start="2025-06-20T06:00:00Z", end="2025-06-20T07:00:00Z")
    # Queries 08:00-09:00 server time; timestamps come back as "...+02:00"
```

Aggregate values (AVG, MIN, MAX, RNG) are stamped at the end of their period.

### Logging

aspy21 logs through the standard `logging` module under the `aspy21` logger. To print its
messages with a timestamped format:

```python
from aspy21 import configure_logging

configure_logging("INFO")  # DEBUG, INFO, WARNING (default), ERROR or CRITICAL
configure_logging()        # level from the ASPEN_LOG_LEVEL environment variable
```

At `DEBUG`, every request is logged with its SQL query and the start of the response.
Applications that configure logging themselves can set the level of the `aspy21` logger
instead.

### Retries

Requests that fail for a reason likely to pass are repeated, up to `retries` times
(default: 2, so at most 3 attempts):

- **Retried**: connection errors (refused, reset, dropped), connect timeouts, and HTTP 429,
  502, 503 and 504
- **Not retried**: read timeouts (a query slow enough to time out usually times out again,
  and repeating it adds load on the historian), other HTTP errors such as 401 or 500, and
  SQL errors (`AspenSqlError`)

Between attempts the client waits 0.5s, then 1s, 2s and so on up to 8s. If the server sends
a `Retry-After` header (in seconds), that wait is used instead, up to 30s. Each retry is
logged as a warning. When all attempts fail, the error from the last one is raised.

```python
# More attempts for an unreliable network
client = AspenClient(base_url=..., datasource="IP21", retries=5)

# Fail fast, no retries
client = AspenClient(base_url=..., datasource="IP21", retries=0)
```

Retries apply to every request, including those sent through a custom `http_client`.

---

## Error Handling

IP.21 reports most errors with HTTP 200 and the error in the response body. These are
raised as `AspenError`:

- `AspenSqlError` - the SQL endpoint rejected a query (reads, search by description) or
  returned a response that could not be read
- `AspenBrowseError` - the Browse endpoint (search by tag name) reported an error or
  returned a response that could not be read

`AspenError` is a subclass of `ValueError`. Invalid arguments, such as an empty tag list
or a client without `datasource`, raise a plain `ValueError`.

```python
from aspy21 import AspenClient, AspenError, OutputFormat
import httpx

try:
    with AspenClient(
        base_url="http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
        auth=("user", "password"),
        datasource="IP21"
    ) as client:
        df = client.read(
            ["TEMP_201"],
            start="2025-06-20 08:00:00",
            end="2025-06-20 09:00:00",
            output=OutputFormat.DATAFRAME,
        )
except AspenError as e:
    print(f"IP.21 reported an error: {e}")  # Returned by the server with HTTP 200
except ValueError as e:
    print(f"Invalid request: {e}")  # e.g. no datasource
except httpx.HTTPStatusError as e:
    print(f"HTTP error: {e.response.status_code}")
except httpx.RequestError as e:
    print(f"Connection error: {e}")
```

---

## Development

### Running Tests

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=src/aspy21 --cov-report=html
```

### Type Checking

```bash
pyright
```

### Code Formatting

```bash
ruff format
```

---

## Dependencies

### Core Dependencies

- **httpx** (>= 0.27) - HTTP client with async support
- **pandas** (>= 2.0) - DataFrame output and date parsing
- **tenacity** (>= 9.0) - Retries of transient failures

### Development Dependencies

- pytest, pytest-cov - Testing framework
- respx - HTTP mocking for tests
- ruff - Code formatting and linting
- pyright - Static type checking
- pre-commit - Git hooks

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) file for details.

---

## Contributing

Contributions are welcome. Please ensure:

1. All tests pass (`pytest`)
2. Code is formatted (`ruff format`)
3. Type checking passes (`pyright`)
4. Coverage remains above 85%

---

## Support

For issues, questions, or feature requests, please open an issue on [GitHub](https://github.com/bazdalaz/aspy21/issues).

---

## Disclaimer

This project is an independent open-source client library and is not affiliated with, endorsed by, or sponsored by AspenTech. "Aspen InfoPlus.21", "IP.21", and "AspenTech" are trademarks or registered trademarks of Aspen Technology, Inc.

This software interacts with Aspen InfoPlus.21 systems through their documented REST API endpoints. Users must have appropriate licenses and authorization to access AspenTech systems.

Users are responsible for compliance with their AspenTech license agreements and applicable terms of service. This library merely provides a technical interface and does not grant any rights to AspenTech software or services.
