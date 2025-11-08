"""Integration tests for caching with AspenClient."""

import httpx
import pandas as pd
import pytest
import respx

from aspy21 import AspenCache, AspenClient, CacheConfig, OutputFormat, ReaderType


class TestAspenClientCache:
    """Test caching integration with AspenClient."""

    def test_client_no_cache_by_default(self):
        """Test that cache is disabled by default."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        assert client._cache is None
        assert client.get_cache_stats() is None

        client.close()

    def test_client_enable_cache_with_true(self):
        """Test enabling cache with cache=True."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
            cache=True,
        )

        assert client._cache is not None
        stats = client.get_cache_stats()
        assert stats is not None
        assert stats["enabled"] is True

        client.close()

    def test_client_enable_cache_with_config(self):
        """Test enabling cache with custom config."""
        config = CacheConfig(max_size=500, ttl_search=1200)
        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
            cache=config,
        )

        assert client._cache is not None
        assert client._cache.config.max_size == 500
        assert client._cache.config.ttl_search == 1200

        client.close()

    def test_client_use_existing_cache(self):
        """Test using existing cache instance."""
        shared_cache = AspenCache()

        client1 = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
            cache=shared_cache,
        )

        client2 = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
            cache=shared_cache,
        )

        # Both clients share the same cache
        assert client1._cache is client2._cache is shared_cache

        client1.close()
        client2.close()

    def test_client_cache_invalid_type_raises_error(self):
        """Test that invalid cache parameter raises TypeError."""
        with pytest.raises(TypeError, match="cache must be"):
            AspenClient(
                base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
                cache="invalid",  # type: ignore[arg-type]
            )

    @respx.mock
    def test_read_caches_historical_data(self, mock_api):
        """Test that historical data is cached."""
        # Mock SQL response
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"ts": "2025-01-01T00:00:00Z", "name": "TAG1", "value": 10.5, "quality": 0},
                    {"ts": "2025-01-01T01:00:00Z", "name": "TAG1", "value": 11.5, "quality": 0},
                ],
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            timeout=2,
            verify_ssl=False,
            datasource="IP21",
            cache=True,
        )

        # First call - should hit API
        result1 = client.read(
            ["TAG1"],
            start="2025-01-01 00:00:00",
            end="2025-01-01 02:00:00",
            read_type=ReaderType.INT,
            output=OutputFormat.JSON,
        )

        # Second call with same parameters - should hit cache
        result2 = client.read(
            ["TAG1"],
            start="2025-01-01 00:00:00",
            end="2025-01-01 02:00:00",
            read_type=ReaderType.INT,
            output=OutputFormat.JSON,
        )

        # Should have only made 1 API call
        assert len(mock_api.calls) == 1

        # Results should be identical
        assert result1 == result2

        # Cache stats should show hit
        stats = client.get_cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate_percent"] == 50.0

        client.close()

    @respx.mock
    def test_read_does_not_cache_current_data(self, mock_api):
        """Test that current/future data is not cached with long TTL."""
        from datetime import datetime

        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"ts": datetime.now().isoformat(), "name": "TAG1", "value": 10.5},
                ],
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
            cache=True,
        )

        # Read current data (end time is now)
        now = datetime.now().isoformat()
        client.read(["TAG1"], start=now, end=now, output=OutputFormat.JSON)

        # Second call - should NOT be cached (current data)
        client.read(["TAG1"], start=now, end=now, output=OutputFormat.JSON)

        # Should make 2 API calls (no caching for current data)
        assert len(mock_api.calls) == 2

        client.close()

    @respx.mock
    def test_read_dataframe_caching(self, mock_api):
        """Test caching works with DataFrame output."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"ts": "2025-01-01T00:00:00Z", "name": "TAG1", "value": 10.5, "quality": 0},
                ],
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
            cache=True,
        )

        # Read as DataFrame
        df1 = client.read(
            ["TAG1"],
            start="2025-01-01 00:00:00",
            end="2025-01-01 01:00:00",
            output=OutputFormat.DATAFRAME,
        )

        # Second call - cached
        df2 = client.read(
            ["TAG1"],
            start="2025-01-01 00:00:00",
            end="2025-01-01 01:00:00",
            output=OutputFormat.DATAFRAME,
        )

        # Only 1 API call
        assert len(mock_api.calls) == 1

        # DataFrames should be equal
        assert isinstance(df1, pd.DataFrame)
        assert isinstance(df2, pd.DataFrame)
        pd.testing.assert_frame_equal(df1, df2)

        client.close()

    @respx.mock
    def test_search_caching(self, mock_api):
        """Test that search results are cached."""
        mock_api.get("https://aspen.local/ProcessData/AtProcessDataREST.dll/Browse").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "tags": [
                            {"t": "TEMP_101", "n": "Temperature 101"},
                            {"t": "TEMP_102", "n": "Temperature 102"},
                        ]
                    }
                },
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
            cache=True,
        )

        # First search
        tags1 = client.search(tag="TEMP*")

        # Second search with same pattern - should be cached
        tags2 = client.search(tag="TEMP*")

        # Only 1 API call
        assert len(mock_api.calls) == 1

        # Results should be identical
        assert tags1 == tags2
        assert len(tags1) == 2

        # Cache hit
        stats = client.get_cache_stats()
        assert stats["hits"] == 1

        client.close()

    @respx.mock
    def test_different_parameters_different_cache(self, mock_api):
        """Test that different parameters create separate cache entries."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(200, json=[])
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
            cache=True,
        )

        # Different tags
        client.read(["TAG1"], start="2025-01-01", end="2025-01-02")
        client.read(["TAG2"], start="2025-01-01", end="2025-01-02")

        # Different time ranges
        client.read(["TAG1"], start="2025-01-03", end="2025-01-04")

        # Different read types
        client.read(["TAG1"], start="2025-01-01", end="2025-01-02", read_type=ReaderType.RAW)

        # Should have made 4 API calls (no cache hits due to different params)
        assert len(mock_api.calls) == 4

        client.close()

    def test_clear_cache(self):
        """Test clearing cache."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
            cache=True,
        )

        # Manually add to cache
        client._cache.set("test", "value", key=1)
        client._cache.set("test", "value", key=2)

        stats = client.get_cache_stats()
        assert stats["size"] == 2

        # Clear cache
        count = client.clear_cache()

        assert count == 2
        stats = client.get_cache_stats()
        assert stats["size"] == 0

        client.close()

    def test_invalidate_cache(self):
        """Test invalidating cache entries."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
            cache=True,
        )

        # Manually add cache entries
        client._cache.set("read", "data1", tags=["TAG1"])
        client._cache.set("read", "data2", tags=["TAG2"])

        stats_before = client.get_cache_stats()
        assert stats_before["size"] == 2

        # Invalidate all
        count = client.invalidate_cache()

        assert count == 2
        stats_after = client.get_cache_stats()
        assert stats_after["size"] == 0

        client.close()

    def test_cache_stats_without_cache(self):
        """Test that cache stats methods work when cache is disabled."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
            cache=None,
        )

        assert client.get_cache_stats() is None
        assert client.clear_cache() == 0
        assert client.invalidate_cache() == 0

        client.close()
