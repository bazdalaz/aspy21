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

Basic example showing how to:
- Load configuration from `.env` file
- Configure logging
- Connect to Aspen IP.21 with Basic Authentication
- Read historical data for a tag
- Handle errors

**Run:**
```bash
python examples/basic_usage.py
```

**What it does:**
- Reads configuration from `.env`
- Configures logging based on `ASPEN_LOG_LEVEL`
- Connects to your Aspen server
- Retrieves RAW data for a tag over a time range
- Prints the results as a pandas DataFrame

### search_tags.py

Demonstrates tag search functionality:
- Search by tag name pattern with wildcards (`*` and `?`)
- Search by description
- Combine multiple filters
- Case-insensitive matching

**Run:**
```bash
python examples/search_tags.py
```

**What it does:**
- Shows various wildcard patterns (`TEMP*`, `AI_10?`, etc.)
- Searches by description keywords
- Demonstrates combined tag + description filtering
- Lists matching tags with their descriptions

### search_and_read.py

Demonstrates how to search for tags and then read their historical data:
- Search with `return_desc=False` to get tag names for reading
- Search with descriptions then extract names
- Filter search results before reading
- Read data for dynamically discovered tags

**Run:**
```bash
python examples/search_and_read.py
```

**What it does:**
- Shows 4 different workflows for search → read
- Demonstrates `return_desc=False` for clean tag name lists
- Shows how to filter and select specific tags
- Reads historical data for found tags with different reader types

## Creating Your Own Scripts

```python
from aspy21 import AspenClient, ReaderType, configure_logging

# Optional: configure logging
configure_logging("INFO")

# Connect to Aspen
client = AspenClient(
    base_url="http://your-server/ProcessData/AtProcessDataREST.dll",
    username="your-username",
    password="your-password",
    datasource="your-datasource",  # Optional
)

# Read data
df = client.read(
    tags=["TAG1", "TAG2"],
    start="2025-01-01 00:00:00",
    end="2025-01-01 01:00:00",
    read_type=ReaderType.RAW,
    max_rows=100000,  # Optional, default: 100000
)

print(df)
client.close()
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

**Note**: `search()` requires:
- `tag` parameter (use `"*"` to search all tags)
- `datasource` must be configured in AspenClient

```python
# Search by tag name pattern (wildcards: * and ?)
tags = client.search(tag="TEMP*")  # All tags starting with TEMP

# Search all tags by description
tags = client.search(tag="*", description="pressure")  # All tags with "pressure" in description

# Combine filters
tags = client.search(tag="AI_1*", description="reactor")

# Results are list of dicts
for tag in tags:
    print(f"{tag['name']}: {tag['description']}")
```
