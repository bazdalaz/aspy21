
# Aspy21

**Python Client for Aspen InfoPlus.21 (IP.21)**

[![PyPI version](https://img.shields.io/pypi/v/aspy21.svg)](https://pypi.org/project/aspy21/)
[![Python versions](https://img.shields.io/pypi/pyversions/aspy21.svg)](https://pypi.org/project/aspy21/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/bazdalaz/aspy21/blob/main/LICENSE)
[![Tests](https://github.com/bazdalaz/aspy21/actions/workflows/tests.yml/badge.svg)](https://github.com/bazdalaz/aspy21/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/bazdalaz/aspy21/branch/main/graph/badge.svg)](https://codecov.io/gh/bazdalaz/aspy21)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with pyright](https://microsoft.github.io/pyright/img/pyright_badge.svg)](https://microsoft.github.io/pyright/)

> **Note**: This is an independent, unofficial client library. Not affiliated with AspenTech.

---

## Overview

**aspy21** is a modern, high-performance Python client for Aspen InfoPlus.21 (IP.21) built on the AspenOne ProcessData REST API. It provides unified access to process historian data with pandas DataFrame output, automatic batching, and intelligent retry logic.

### Key Capabilities

- REST-based communication with Aspen IP.21 historian
- Basic HTTP authentication (cross-platform compatible)
- Tag search with wildcards and description filtering
- Unified interface for analog, discrete, and text tags
- Support for RAW, INT, SNAPSHOT, and AVG reader types
- Pandas DataFrame output with optional status columns
- Configurable row limits and query parameters
- Built-in retry logic with exponential backoff
- Type-annotated and fully tested

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
from aspy21 import AspenClient, ReaderType

# Initialize client using context manager (recommended)
with AspenClient(
    base_url="https://aspen.myplant.local/ProcessData",
    auth=("user", "password")
) as client:
    # Read historical data
    df = client.read(
        tags=["ATI111", "AP101.PV"],
        start="2025-06-20 08:00:00",
        end="2025-06-20 09:00:00",
        interval=600,
        read_type=ReaderType.RAW,
        as_df=True,
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

### read() Method

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tags` | Iterable[str] | required | List of tag names to retrieve |
| `start` | str\|None | None | Start timestamp (ISO format). When omitted, falls back to a SNAPSHOT read. |
| `end` | str\|None | None | End timestamp (ISO format). When omitted, falls back to a SNAPSHOT read. |
| `interval` | int\|None | None | Interval in seconds for aggregated data |
| `read_type` | ReaderType | INT | Data retrieval mode (auto-coerced to SNAPSHOT if no range provided) |
| `include_status` | bool | False | Include a `<tag>_status` column (historical status or snapshot quality) |
| `max_rows` | int | 100000 | Maximum rows to return per tag |
| `with_description` | bool | False | Request tag descriptions (`ip_description`) alongside values |
| `as_df` | bool | False | Return results as a pandas DataFrame instead of JSON list |

**Returns**:
- If `as_df=True`: pandas.DataFrame with time index and columns for each tag.
- If `as_df=False`: List of dictionaries including `timestamp`, `tag`, `value`, and optional `description`/`status`.

> **Snapshot reads:**
> - Supplying no `start`/`end` (or explicitly choosing `ReaderType.SNAPSHOT`) issues a snapshot SQL query that returns the latest value plus `ip_description`.
> - When `include_status=True`, the snapshot response also includes the `ip_input_quality` code, exposed as a `<tag>_status` column (and as `status` in JSON output when `as_df=False`) alongside the value. The timestamp reflects the request time.

### search() Method

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tag` | str | `"*"` | Tag name pattern with wildcards (`*`, `?`). Defaults to `"*"` (all tags). |
| `description` | str\|None | None | Description filter (case-insensitive substring). When provided, uses SQL endpoint for server-side search. |
| `case_sensitive` | bool | False | Whether tag matching is case-sensitive (Browse endpoint only) |
| `max_results` | int | 10000 | Maximum number of results to return |
| `return_desc` | bool | True | Whether to return descriptions. If True, returns dicts. If False, returns tag names only. |

**Returns**:
- If `return_desc=True`: List of dicts with 'name' and 'description' keys
- If `return_desc=False`: List of tag name strings

**Requirements**:
- `datasource` must be configured in AspenClient

**Search Modes**:
- **Tag-only search** (no description): Uses Browse endpoint for fast tag name matching
- **Description search** (description provided): Uses SQL endpoint for server-side description filtering

**Wildcards**:
- `*` - Matches any number of characters
- `?` - Matches exactly one character

**Examples**:
```python
# Find all temperature tags with descriptions (Browse endpoint)
tags = client.search(tag="TEMP*")
# Returns: [{"name": "TEMP_101", "description": "Reactor temp"}, ...]

# Get just tag names without descriptions
tag_names = client.search(tag="TEMP*", return_desc=False)
# Returns: ["TEMP_101", "TEMP_102", ...]

# Search by description only (SQL endpoint)
reactor_tags = client.search(description="reactor")

# Combine tag pattern and description (SQL endpoint)
pressure_tags = client.search(tag="AI_1*", description="pressure")
```

### ReaderType Enum

Available reader types:

- `ReaderType.RAW` - Raw data points as stored
- `ReaderType.INT` - Interpolated values at intervals
- `ReaderType.SNAPSHOT` - Current snapshot of tag values
- `ReaderType.AVG` - Average values over intervals

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
from aspy21 import AspenClient
import httpx

try:
    with AspenClient(
        base_url="https://aspen.example.com/ProcessData",
        auth=("user", "password")
    ) as client:
        df = client.read(
            tags=["ATI111"],
            start="2025-06-20 08:00:00",
            end="2025-06-20 09:00:00",
            as_df=True,
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
