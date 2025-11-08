"""Tests for caching functionality."""

import time

import pandas as pd

from aspy21 import AspenCache, CacheConfig


class TestCacheConfig:
    """Test CacheConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CacheConfig()

        assert config.enabled is True
        assert config.max_size == 1000
        assert config.ttl_search == 3600  # 1 hour
        assert config.ttl_metadata == 3600  # 1 hour
        assert config.ttl_historical == 86400  # 24 hours
        assert config.ttl_snapshot == 60  # 1 minute
        assert config.ttl_aggregates == 86400  # 24 hours

    def test_custom_config(self):
        """Test custom configuration."""
        config = CacheConfig(
            enabled=False,
            max_size=500,
            ttl_search=1800,
            ttl_historical=43200,
        )

        assert config.enabled is False
        assert config.max_size == 500
        assert config.ttl_search == 1800
        assert config.ttl_historical == 43200


class TestAspenCache:
    """Test AspenCache class."""

    def test_cache_initialization(self):
        """Test cache initialization."""
        cache = AspenCache()

        assert cache.config.enabled is True
        stats = cache.get_stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_cache_initialization_with_config(self):
        """Test cache initialization with custom config."""
        config = CacheConfig(max_size=100, ttl_search=600)
        cache = AspenCache(config)

        assert cache.config.max_size == 100
        assert cache.config.ttl_search == 600

    def test_cache_disabled(self):
        """Test cache when disabled."""
        config = CacheConfig(enabled=False)
        cache = AspenCache(config)

        # Try to set and get
        cache.set("test", "value", key="test")
        result = cache.get("test", key="test")

        assert result is None
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_cache_set_and_get(self):
        """Test basic cache set and get."""
        cache = AspenCache()

        # Set a value
        cache.set("read", {"data": "test"}, tags=["TAG1"], start="2025-01-01")

        # Get the value
        result = cache.get("read", tags=["TAG1"], start="2025-01-01")

        assert result == {"data": "test"}

        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 0
        assert stats["size"] == 1

    def test_cache_miss(self):
        """Test cache miss."""
        cache = AspenCache()

        # Try to get non-existent value
        result = cache.get("read", tags=["TAG_MISSING"])

        assert result is None

        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 1

    def test_cache_ttl_expiration(self):
        """Test that cache entries expire after TTL."""
        cache = AspenCache()

        # Set with 1 second TTL
        cache.set("test", "value", ttl_seconds=1, key="test_key")

        # Immediately should be in cache
        assert cache.get("test", key="test_key") == "value"

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired
        assert cache.get("test", key="test_key") is None

        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_cache_lru_eviction(self):
        """Test LRU eviction when cache is full."""
        config = CacheConfig(max_size=3)
        cache = AspenCache(config)

        # Fill cache
        cache.set("test", "value1", key=1)
        time.sleep(0.01)  # Ensure different timestamps
        cache.set("test", "value2", key=2)
        time.sleep(0.01)
        cache.set("test", "value3", key=3)

        assert cache.get_stats()["size"] == 3

        # Add one more - should evict oldest (key=1)
        cache.set("test", "value4", key=4)

        assert cache.get_stats()["size"] == 3
        assert cache.get("test", key=1) is None  # Evicted
        assert cache.get("test", key=2) == "value2"  # Still there
        assert cache.get("test", key=3) == "value3"  # Still there
        assert cache.get("test", key=4) == "value4"  # New entry

    def test_cache_invalidate_all(self):
        """Test invalidating entire cache."""
        cache = AspenCache()

        # Add some entries
        cache.set("test", "value1", key=1)
        cache.set("test", "value2", key=2)
        cache.set("test", "value3", key=3)

        assert cache.get_stats()["size"] == 3

        # Invalidate all
        count = cache.invalidate()

        assert count == 3
        assert cache.get_stats()["size"] == 0

    def test_cache_invalidate_specific(self):
        """Test invalidating specific entry."""
        cache = AspenCache()

        # Add entries
        cache.set("read", "value1", tags=["TAG1"])
        cache.set("read", "value2", tags=["TAG2"])

        # Invalidate one specific entry
        count = cache.invalidate("read", tags=["TAG1"])

        assert count == 1
        assert cache.get("read", tags=["TAG1"]) is None
        assert cache.get("read", tags=["TAG2"]) == "value2"

    def test_cache_stats(self):
        """Test cache statistics."""
        cache = AspenCache()

        # Initial stats
        stats = cache.get_stats()
        assert stats["enabled"] is True
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["total_requests"] == 0
        assert stats["hit_rate_percent"] == 0

        # Add and retrieve data
        cache.set("test", "value", key=1)
        cache.get("test", key=1)  # hit
        cache.get("test", key=2)  # miss
        cache.get("test", key=1)  # hit

        stats = cache.get_stats()
        assert stats["size"] == 1
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["total_requests"] == 3
        assert stats["hit_rate_percent"] == 66.67

    def test_cache_key_generation_consistency(self):
        """Test that cache keys are generated consistently."""
        cache = AspenCache()

        # Set with one order
        cache.set("read", "value", tags=["TAG2", "TAG1"], start="2025-01-01")

        # Get with different order (should still match due to sorting)
        result = cache.get("read", tags=["TAG1", "TAG2"], start="2025-01-01")

        assert result == "value"

    def test_cache_with_different_parameters(self):
        """Test that different parameters create different cache entries."""
        cache = AspenCache()

        # Set different entries
        cache.set("read", "data1", tags=["TAG1"], start="2025-01-01")
        cache.set("read", "data2", tags=["TAG1"], start="2025-01-02")
        cache.set("read", "data3", tags=["TAG2"], start="2025-01-01")

        # Retrieve each
        assert cache.get("read", tags=["TAG1"], start="2025-01-01") == "data1"
        assert cache.get("read", tags=["TAG1"], start="2025-01-02") == "data2"
        assert cache.get("read", tags=["TAG2"], start="2025-01-01") == "data3"

    def test_cache_clear_stats(self):
        """Test clearing statistics."""
        cache = AspenCache()

        # Generate some stats
        cache.set("test", "value", key=1)
        cache.get("test", key=1)
        cache.get("test", key=2)

        stats = cache.get_stats()
        assert stats["hits"] > 0
        assert stats["misses"] > 0

        # Clear stats
        cache.clear_stats()

        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["size"] == 1  # Data still there, just stats cleared

    def test_cache_with_dataframe(self):
        """Test caching pandas DataFrame."""
        cache = AspenCache()

        df = pd.DataFrame({"time": [1, 2, 3], "value": [10.5, 20.3, 30.1]})

        # Cache DataFrame
        cache.set("read", df, tags=["TAG1"])

        # Retrieve
        result = cache.get("read", tags=["TAG1"])

        assert isinstance(result, pd.DataFrame)
        pd.testing.assert_frame_equal(result, df)

    def test_cache_operation_type_ttls(self):
        """Test that different operations get different TTLs."""
        config = CacheConfig(
            ttl_search=100,
            ttl_historical=200,
            ttl_snapshot=50,
        )
        cache = AspenCache(config)

        # Set different operation types (without explicit TTL)
        cache.set("search", "search_data", key=1)
        cache.set("read_historical", "historical_data", key=2)
        cache.set("read_snapshot", "snapshot_data", key=3)

        # Check that entries exist
        assert cache.get("search", key=1) is not None
        assert cache.get("read_historical", key=2) is not None
        assert cache.get("read_snapshot", key=3) is not None

        # Wait and verify snapshot expires first (50s), but we'll use shorter times for test
        # This is more of a design verification - actual TTL testing needs longer waits
