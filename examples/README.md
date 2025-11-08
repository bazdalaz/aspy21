# Examples

This directory contains example scripts demonstrating how to use aspy21.

## Setup

1. Copy `.env.example` from the project root to `.env` in the project root:
   ```bash
   cp ../.env.example ../.env
   ```

2. Edit `.env` with your actual Aspen server details:
   ```env
   ASPEN_BASE_URL=http://YOUR_SERVER/ProcessData/AtProcessDataREST.dll
   ASPEN_USERNAME=yourusername
   ASPEN_PASSWORD=yourpassword
   ASPEN_DATASOURCE=datasource_name
   ASPEN_LOG_LEVEL=INFO
   ```

3. Install the package with examples dependencies (from project root):
   ```bash
   pip install -e ".[examples]"
   ```

   Or if you already have python-dotenv installed:
   ```bash
   pip install -e .
   ```

## Examples

### basic_usage.py

Basic example demonstrating core functionality:
- Load configuration from `.env` file using python-dotenv
- Configure logging from environment variable
- Connect to Aspen IP.21 with Basic Authentication
- Read historical data for tags over a time range
- Error handling and connection management

**Run:**
```bash
python examples/basic_usage.py
```

**What it does:**
- Loads environment variables from `.env` file
- Configures logging level based on `ASPEN_LOG_LEVEL`
- Creates an AspenClient with context manager (auto-cleanup)
- Reads test tags specified in `ASPEN_TEST_TAGS` environment variable
- Retrieves data for 1-hour period (1-NOV-25 8:00-9:00)
- Outputs results as a pandas DataFrame
- Demonstrates proper error handling with try/except

**Environment variables used:**
- `ASPEN_BASE_URL` - Server endpoint URL
- `ASPEN_USERNAME` - Username for authentication
- `ASPEN_PASSWORD` - Password for authentication
- `ASPEN_DATASOURCE` - Datasource name (optional, uses server default if empty)
- `ASPEN_TIMEOUT` - Request timeout in seconds (default: 60.0)
- `ASPEN_VERIFY_SSL` - SSL certificate verification (default: False)
- `ASPEN_LOG_LEVEL` - Logging level (INFO, DEBUG, etc.)
- `ASPEN_TEST_TAGS` - Comma-separated list of tag names to read

### caching_example.py

Demonstrates caching functionality to reduce API load and improve performance:
- Enable caching with default configuration
- Custom cache configuration with TTLs
- Cache management (stats, clear, invalidate)
- Smart caching (historical vs current data)

**Run:**
```bash
python examples/caching_example.py
```

**What it does:**
- **Example 1**: Basic caching with defaults
  - Shows cache miss (first API call) vs cache hit (second call)
  - Demonstrates 10-100x speedup for cached queries
  - Displays cache statistics (hits, misses, hit rate)
  
- **Example 2**: Custom cache configuration with `CacheConfig`
  - Sets custom TTLs for different operation types
  - Configures max cache size (500 entries)
  - Shows cache behavior for search operations
  
- **Example 3**: Cache management operations
  - Get cache statistics
  - Clear entire cache
  - Invalidate specific cache entries
  
- **Example 4**: Smart caching behavior
  - Historical data cached with long TTL (24 hours)
  - Current/recent data uses short TTL or no caching
  - Demonstrates intelligent cache strategy

**Key concepts demonstrated:**
- `cache=True` - Enable with default settings
- `cache=CacheConfig(...)` - Custom configuration
- `get_cache_stats()` - View cache performance metrics
- `clear_cache()` - Remove all cached entries
- `invalidate_cache()` - Remove specific entries
- Performance improvements: 60-80% API load reduction, 10-100x speedup

### search_and_read.py

Comprehensive example demonstrating tag search and hybrid mode:
- Search-only mode: find tags then read separately
- Hybrid mode: search and read in a single operation
- Multiple search patterns and filters
- Different reader types and intervals

**Run:**
```bash
python examples/search_and_read.py
```

**What it does:**
- **Example 1**: Search for tags matching pattern, get tag names, then read data separately
  - Uses `include=IncludeFields.NONE` to return `list[str]` of tag names
  - Reads 1 hour of raw data for found tags
  
- **Example 2**: Hybrid mode with tag pattern search
  - Uses tag pattern `NAI*` to search for tags
  - Reads interpolated data with 10-minute intervals in single operation
  - Demonstrates `read_type=ReaderType.INT` with `interval=600`
  
- **Example 3**: Hybrid mode with description filter
  - Searches by description keyword `V1-01`
  - Reads interpolated data with 1-hour intervals
  - Shows how to combine search filters with data reading
  
- **Example 4**: Search broadly, filter results, then read
  - Searches with broad pattern and description filter
  - Uses `include=IncludeFields.DESCRIPTION` to get tag metadata
  - Filters results programmatically (selects TI/PI tags only)
  - Reads raw data for filtered tag subset

**Key concepts demonstrated:**
- `IncludeFields.NONE` - Returns `list[str]` of tag names only
- `IncludeFields.DESCRIPTION` - Returns `list[dict[str, str]]` with name + description
- Hybrid mode - Combines search and read in one call (when `start`/`end` provided)
- Different reader types: `RAW`, `INT` (interpolated)
- Interval-based reads for aggregated/interpolated data

## Creating Your Own Scripts

```python
from aspy21 import AspenClient, ReaderType, configure_logging

# Optional: configure logging
configure_logging("INFO")

# Connect to Aspen using context manager (recommended)
with AspenClient(
    base_url="http://your-server/ProcessData/AtProcessDataREST.dll",
    auth=("your-username", "your-password"),
    datasource="IP21",  # Required for historical reads
) as client:
    # Read data
    df = client.read(
        tags=["TAG1", "TAG2"],
        start="2025-01-01 00:00:00",
        end="2025-01-01 01:00:00",
        read_type=ReaderType.RAW,
        max_rows=100000,  # Optional, default: 100000
    )
    
    print(df)
    # Connection automatically closed at end of 'with' block
```

## Reader Types

- `ReaderType.RAW` - Raw data as stored
- `ReaderType.INT` - Interpolated data
- `ReaderType.SNAPSHOT` - Current snapshot
- `ReaderType.AVG` - Averaged data (requires `interval` parameter)

## Aggregated Data Example

```python
# Get 10-minute averages
df = client.read(
    tags=["TAG1"],
    start="2025-01-01 00:00:00",
    end="2025-01-02 00:00:00",
    read_type=ReaderType.AVG,
    interval=600,  # 10 minutes in seconds
)
```

## Searching for Tags

**Note**: `search()` requires `datasource` to be configured in AspenClient

```python
from aspy21 import IncludeFields

# Search by tag name pattern (wildcards: * and ?)
# Default: returns list[str] of tag names only
tags = client.search(tag="TEMP*")  # All tags starting with TEMP
# Returns: ['TEMP01', 'TEMP02', 'TEMP_REACTOR', ...]

# Search with descriptions - returns list of dicts
tags = client.search(tag="TEMP*", include=IncludeFields.DESCRIPTION)
# Returns: [{'name': 'TEMP01', 'description': 'Temperature sensor 1'}, ...]

# Search all tags by description keyword
tags = client.search(description="pressure", include=IncludeFields.DESCRIPTION)

# Combine tag pattern and description filters
tags = client.search(tag="AI_1*", description="reactor", include=IncludeFields.DESCRIPTION)

# Process results with descriptions
for tag in tags:
    print(f"{tag['name']}: {tag['description']}")

# Use BOTH to get all available fields (name, description, maptype)
tags = client.search(tag="*", limit=10, include=IncludeFields.BOTH)
```
