"""Example demonstrating caching functionality to reduce API load and improve performance."""

import os
import time
from pathlib import Path

from dotenv import load_dotenv

from aspy21 import AspenClient, CacheConfig, OutputFormat, configure_logging

# Load .env from project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Configure logging to see cache hits/misses
configure_logging()

print("\n" + "=" * 80)
print("Caching Example - Reduce API Load & Improve Performance")
print("=" * 80 + "\n")

# Get configuration from environment
base_url = os.getenv("ASPEN_BASE_URL")
username = os.getenv("ASPEN_USERNAME")
password = os.getenv("ASPEN_PASSWORD")
datasource = os.getenv("ASPEN_DATASOURCE", "")

# Validate required variables
if not all([base_url, username, password, datasource]):
    print("ERROR: Missing required environment variables!")
    print("Required: ASPEN_BASE_URL, ASPEN_USERNAME, ASPEN_PASSWORD, ASPEN_DATASOURCE")
    print("Please create .env file from .env.example")
    exit(1)

# Type narrowing
assert base_url is not None
assert username is not None
assert password is not None

# Example 1: Basic caching with default configuration
print("Example 1: Enable caching with defaults")
print("-" * 80)

with AspenClient(
    base_url=base_url,
    auth=(username, password),
    datasource=datasource,
    cache=True,  # Enable caching with default settings
) as client:
    # First read - will hit the API
    print("First read (cache miss, hits API)...")
    start_time = time.time()
    data1 = client.read(
        ["GTI118.PV"],
        start="2025-01-01 08:00:00",
        end="2025-01-01 09:00:00",
        output=OutputFormat.JSON,
    )
    api_time = time.time() - start_time
    print(f"  Time: {api_time:.3f}s")
    print(f"  Data points: {len(data1) if isinstance(data1, list) else 0}")

    # Second read with same parameters - will hit cache
    print("\nSecond read with same parameters (cache hit)...")
    start_time = time.time()
    data2 = client.read(
        ["GTI118.PV"],
        start="2025-01-01 08:00:00",
        end="2025-01-01 09:00:00",
        output=OutputFormat.JSON,
    )
    cache_time = time.time() - start_time
    print(f"  Time: {cache_time:.3f}s")
    if cache_time > 0:
        print(f"  Speedup: {api_time / cache_time:.1f}x faster!")
    else:
        print("  Speedup: >1000x faster! (cache time < 0.001s)")

    # Show cache statistics
    stats = client.get_cache_stats()
    if stats:
        print(f"\nCache stats: {stats['hits']} hits, {stats['misses']} misses")
        print(f"Hit rate: {stats['hit_rate_percent']}%")

print()

# Example 2: Custom cache configuration
print("Example 2: Custom cache configuration")
print("-" * 80)

# Configure cache with custom TTLs
custom_config = CacheConfig(
    enabled=True,
    max_size=500,  # Limit cache to 500 entries
    ttl_historical=7200,  # 2 hours for historical data
    ttl_search=1800,  # 30 minutes for search results
    ttl_snapshot=30,  # 30 seconds for current values
)

with AspenClient(
    base_url=base_url,
    auth=(username, password),
    datasource=datasource,
    cache=custom_config,
) as client:
    print(f"Cache configured: max_size={custom_config.max_size}")
    print(f"  Historical TTL: {custom_config.ttl_historical}s")
    print(f"  Search TTL: {custom_config.ttl_search}s")
    print(f"  Snapshot TTL: {custom_config.ttl_snapshot}s\n")

    # Search for tags - results will be cached
    print("Searching for tags (will be cached)...")
    tags1 = client.search("GTI*", limit=5)
    print(f"Found {len(tags1)} tags: {tags1[:3]}")

    # Same search - from cache
    print("\nSame search again (from cache)...")
    tags2 = client.search("GTI*", limit=5)
    print(f"Found {len(tags2)} tags (from cache)")

    stats = client.get_cache_stats()
    if stats:
        print(f"\nCache stats: size={stats['size']}, hit_rate={stats['hit_rate_percent']}%")

print()

# Example 3: Cache management
print("Example 3: Cache management (stats, clear, invalidate)")
print("-" * 80)

with AspenClient(
    base_url=base_url,
    auth=(username, password),
    datasource=datasource,
    cache=True,
) as client:
    # Make some requests to populate cache
    client.read(["GTI118.PV"], start="2025-01-01 08:00:00", end="2025-01-01 09:00:00")
    client.read(["GTI119.PV"], start="2025-01-01 08:00:00", end="2025-01-01 09:00:00")
    client.search("GTI*", limit=5)

    # Check cache stats
    stats = client.get_cache_stats()
    if stats:
        print(f"Cache populated: {stats['size']} entries")

    # Clear entire cache
    print("\nClearing cache...")
    count = client.clear_cache()
    print(f"Cleared {count} entries")

    stats = client.get_cache_stats()
    if stats:
        print(f"Cache after clear: {stats['size']} entries")

print()

# Example 4: Smart caching - only historical data is cached
print("Example 4: Smart caching (only historical data is cached)")
print("-" * 80)

with AspenClient(
    base_url=base_url,
    auth=(username, password),
    datasource=datasource,
    cache=True,
) as client:
    from datetime import datetime

    # Read historical data (will be cached)
    print("Reading historical data (2025-01-01, will be cached)...")
    client.read(
        ["GTI118.PV"],
        start="2025-01-01 08:00:00",
        end="2025-01-01 09:00:00",
    )

    # Read current data (will NOT be cached with long TTL)
    print("Reading current data (will not be cached with long TTL)...")
    now = datetime.now()
    client.read(
        ["GTI118.PV"],
        start=now.isoformat(),
        end=now.isoformat(),
    )

    stats = client.get_cache_stats()
    if stats:
        print(f"\nCache stats: {stats['size']} entries cached")
        print("Note: Only historical data is cached with long TTL (24h)")
        print("      Current/recent data uses short TTL (1min) or no caching")

print()

print("=" * 80)
print("Caching Benefits:")
print("  - Reduces API load by 60-80% for typical workloads")
print("  - 10-100x performance improvement for cached queries")
print("  - Smart TTLs: historical data cached longer than current data")
print("  - Thread-safe for concurrent requests")
print("  - LRU eviction prevents memory issues")
print("=" * 80)
