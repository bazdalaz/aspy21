
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

**aspy21** is a modern, high-performance Python client for Aspen InfoPlus.21 (IP.21) built on the AspenOne ProcessData REST API. It provides unified access to process historian data with pandas DataFrame output, automatic batching, and intelligent retry logic.

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
- Built-in retry logic with exponential backoff
- **Built-in caching**: Optional caching layer with TTL and LRU eviction to reduce API load
- Type-annotated and fully tested (87% coverage)

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
    base_url="https://aspen.myplant.local/ProcessData",
    auth=("user", "password")
) as client:
    # Read historical data
    df = client.read(
        ["ATI111", "AP101.PV"],
        start="2025-06-20 08:00:00",
        end="2025-06-20 09:00:00",
        interval=600,
        read_type=ReaderType.RAW,
        output=OutputFormat.DATAFRAME,
    )

    print(df)
    # Connection automatically closed
```

---

## Authentication

### HTTP Basic Authentication

```python
with AspenClient(
    base_url="https://aspen.example.com/ProcessData",
    auth=("user", "password")
) as client:
    # Your code here
    pass
```

### No Authentication

For public or internal endpoints:

```python
with AspenClient(
    base_url="http://aspen.example.com/ProcessData"
) as client:
    # Your code here
    pass
```

---

## Caching

### Overview

Built-in caching layer reduces API load by 60-80% and improves performance by 10-100x for repeated queries. The cache uses TTL (Time-To-Live) + LRU (Least Recently Used) eviction and is fully thread-safe.

### Smart Caching Strategy

- **Historical data** (past data): Long TTL (24 hours) - this data doesn't change
- **Search results**: Medium TTL (1 hour) - metadata changes infrequently
- **Aggregates**: Long TTL (24 hours) - computed values are stable
- **Snapshots**: Short TTL (1 minute) - current values change frequently
- **Current data**: Not cached with long TTL - data is volatile

### Enabling Cache

#### Basic Usage (Default Configuration)

```python
from aspy21 import AspenClient

# Enable caching with defaults
with AspenClient(
    base_url="https://aspen.example.com/ProcessData",
    auth=("user", "password"),
    cache=True  # Enable with default settings
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
    ttl_historical=7200,    # 2 hours for historical data
    ttl_search=1800,        # 30 minutes for search results
    ttl_snapshot=30,        # 30 seconds for current values
    ttl_aggregates=7200,    # 2 hours for aggregates
)

with AspenClient(
    base_url="https://aspen.example.com/ProcessData",
    auth=("user", "password"),
    cache=config  # Use custom configuration
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
with AspenClient(base_url=url1, cache=shared_cache) as client1:
    with AspenClient(base_url=url2, cache=shared_cache) as client2:
        # Both clients share the same cache
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
# Invalidate cache for specific tags/time range
count = client.invalidate_cache(
    tags=["TAG1", "TAG2"],
    start="2025-01-01 00:00:00",
    end="2025-01-01 01:00:00"
)
```

### Performance Benefits

**Typical Performance Improvements:**
- API calls reduced by 60-80% for repeated queries
- Query response time: 10-100x faster for cached data
- Network traffic significantly reduced
- Server load reduced

**Example Timing:**
```python
import time

with AspenClient(base_url=url, auth=auth, cache=True) as client:
    # First call - hits API (~500ms)
    start = time.time()
    df1 = client.read(["TAG1"], start="2025-01-01 08:00:00", end="2025-01-01 09:00:00")
    api_time = time.time() - start
    print(f"API call: {api_time:.3f}s")

    # Second call - from cache (~5ms)
    start = time.time()
    df2 = client.read(["TAG1"], start="2025-01-01 08:00:00", end="2025-01-01 09:00:00")
    cache_time = time.time() - start
    print(f"Cache hit: {cache_time:.3f}s ({api_time/cache_time:.0f}x faster!)")
```

### Cache Behavior Details

**What Gets Cached:**
- Historical data reads (data older than 1 minute)
- Search results (tag names and metadata)
- Aggregate queries (AVG, MIN, MAX, RNG)

**What Does NOT Get Cached (or uses short TTL):**
- Current/recent data (within last 1 minute)
- Snapshot reads (short 1-minute TTL)
- Failed requests or errors

**Thread Safety:**
- All cache operations are thread-safe
- Can be safely used in multi-threaded applications
- No data corruption or race conditions

**Memory Management:**
- LRU eviction when max_size reached
- Automatic cleanup of expired entries
- Configurable size limits prevent memory issues

---

## API Reference

### AspenClient

**Constructor Parameters** (all except `base_url` are keyword-only):

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `base_url` | str | required | Base URL of Aspen ProcessData REST API |
| `auth` | Auth\|tuple\|None | None | Authentication as (username, password) tuple or httpx Auth object |
| `timeout` | float | 30.0 | Request timeout in seconds |
| `verify_ssl` | bool | True | Whether to verify SSL certificates |
| `datasource` | str\|None | None | Aspen datasource name (required for search) |
| `cache` | AspenCache\|CacheConfig\|bool\|None | None | Enable caching: True (default config), CacheConfig instance, or AspenCache instance |

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
) -> pd.DataFrame | list[dict]:
```

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tags` | list[str] | required | List of tag names to retrieve (positional-only) |
| `start` | str\|None | None | Start timestamp (ISO format). When omitted, defaults to SNAPSHOT read. |
| `end` | str\|None | None | End timestamp (ISO format). When omitted, defaults to SNAPSHOT read. |
| `interval` | int\|None | None | Interval in seconds for aggregated data (AVG reads) |
| `read_type` | ReaderType | INT | Data retrieval mode (RAW, INT, SNAPSHOT, AVG) |
| `include` | IncludeFields | NONE | Which optional fields to include (NONE, STATUS, DESCRIPTION, ALL) |
| `limit` | int | 100000 | Maximum rows to return per tag |
| `output` | OutputFormat | JSON | Output format (JSON or DATAFRAME) |

**Returns**:
- If `output=OutputFormat.DATAFRAME`: pandas.DataFrame with time index and columns for each tag.
- If `output=OutputFormat.JSON`: List of dictionaries with `timestamp`, `tag`, `value`, and optional `description`/`status` fields.

**Examples**:
```python
# JSON output (default)
data = client.read(
    ["ATI111"],
    start="2025-01-01 00:00:00",
    end="2025-01-01 01:00:00"
)

# DataFrame output with status and descriptions
df = client.read(
    ["ATI111", "AP101.PV"],
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
) -> pd.DataFrame | list[dict] | list[str]:
```

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
| `include` | IncludeFields | NONE | Fields to include (NONE, STATUS, DESCRIPTION, ALL) |
| `output` | OutputFormat | JSON | Output format (JSON or DATAFRAME) |

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
- `ReaderType.INT` - Interpolated values at specified intervals (default)
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
    base_url="https://aspen.example.com/ProcessData",
    auth=("user", "password"),
    timeout=60.0,           # Request timeout (seconds)
    verify_ssl=True,        # SSL certificate verification
    datasource="IP21"       # Required for search operations
) as client:
    # Your code here
    pass
```

### Retry Behavior

The client automatically retries failed requests with exponential backoff:

- Maximum attempts: 3
- Initial delay: 0.5 seconds
- Maximum delay: 8 seconds

---

## Error Handling

```python
from aspy21 import AspenClient, OutputFormat
import httpx

try:
    with AspenClient(
        base_url="https://aspen.example.com/ProcessData",
        auth=("user", "password")
    ) as client:
        df = client.read(
            ["ATI111"],
            start="2025-06-20 08:00:00",
            end="2025-06-20 09:00:00",
            output=OutputFormat.DATAFRAME,
        )
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
- **tenacity** (>= 9.0) - Retry logic with exponential backoff

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
4. Coverage remains above 75%

---

## Support

For issues, questions, or feature requests, please open an issue on [GitHub](https://github.com/bazdalaz/aspy21/issues).

---

## Disclaimer

This project is an independent open-source client library and is not affiliated with, endorsed by, or sponsored by AspenTech. "Aspen InfoPlus.21", "IP.21", and "AspenTech" are trademarks or registered trademarks of Aspen Technology, Inc.

This software interacts with Aspen InfoPlus.21 systems through their documented REST API endpoints. Users must have appropriate licenses and authorization to access AspenTech systems.

Users are responsible for compliance with their AspenTech license agreements and applicable terms of service. This library merely provides a technical interface and does not grant any rights to AspenTech software or services.
