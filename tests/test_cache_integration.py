"""Integration tests for caching with AspenClient."""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
import pandas as pd
import pytest
import respx

from aspy21 import (
    AspenCache,
    AspenClient,
    CacheConfig,
    IncludeFields,
    OutputFormat,
    ReaderType,
)


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
        assert stats is not None
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
        assert stats is not None
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
        assert client._cache is not None
        client._cache.set("test", "value", key=1)
        client._cache.set("test", "value", key=2)

        stats = client.get_cache_stats()
        assert stats is not None
        assert stats["size"] == 2

        # Clear cache
        count = client.clear_cache()

        assert count == 2
        stats = client.get_cache_stats()
        assert stats is not None
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
        assert client._cache is not None
        client._cache.set("read", "data1", tags=["TAG1"])
        client._cache.set("read", "data2", tags=["TAG2"])

        stats_before = client.get_cache_stats()
        assert stats_before is not None
        assert stats_before["size"] == 2

        # Invalidate all
        count = client.invalidate_cache()

        assert count == 2
        stats_after = client.get_cache_stats()
        assert stats_after is not None
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


BASE_URL = "https://aspen.local/ProcessData/AtProcessDataREST.dll"
OTHER_BASE_URL = "https://aspen.local/ProcessData/OtherREST.dll"
START = "2025-01-01 00:00:00"
END = "2025-01-01 02:00:00"

SQL_ROWS = [
    {"ts": "2025-01-01T00:00:00Z", "name": "TAG1", "value": 10.5, "quality": 0},
    {"ts": "2025-01-01T01:00:00Z", "name": "TAG1", "value": 11.5, "quality": 0},
    {"ts": "2025-01-01T00:00:00Z", "name": "TAG2", "value": 20.5, "quality": 0},
    {"ts": "2025-01-01T01:00:00Z", "name": "TAG2", "value": 21.5, "quality": 0},
]

BROWSE_RESPONSE = {
    "data": {
        "tags": [
            {"t": "TEMP_101", "n": "Temperature 101"},
            {"t": "TEMP_102", "n": "Temperature 102"},
        ]
    }
}


def _mock_sql(mock_api, base_url=BASE_URL):
    return mock_api.post(f"{base_url}/SQL").mock(return_value=httpx.Response(200, json=SQL_ROWS))


def _mock_browse(mock_api, base_url=BASE_URL):
    return mock_api.get(f"{base_url}/Browse").mock(
        return_value=httpx.Response(200, json=BROWSE_RESPONSE)
    )


def _client(cache: bool | AspenCache = True, **kwargs: Any) -> AspenClient:
    kwargs.setdefault("base_url", BASE_URL)
    kwargs.setdefault("datasource", "IP21")
    return AspenClient(cache=cache, **kwargs)


class TestReadCacheKey:
    """Every read() argument that changes the result must be part of the cache key."""

    @respx.mock
    def test_json_then_dataframe_not_shared(self, mock_api):
        """A cached JSON result must not be returned for a DataFrame request."""
        _mock_sql(mock_api)
        with _client() as client:
            as_json = client.read(["TAG1"], start=START, end=END, output=OutputFormat.JSON)
            as_df = client.read(["TAG1"], start=START, end=END, output=OutputFormat.DATAFRAME)

        assert isinstance(as_json, list)
        assert isinstance(as_df, pd.DataFrame)
        assert len(mock_api.calls) == 2

    @respx.mock
    def test_dataframe_then_json_not_shared(self, mock_api):
        """A cached DataFrame must not be returned for a JSON request."""
        _mock_sql(mock_api)
        with _client() as client:
            as_df = client.read(["TAG1"], start=START, end=END, output=OutputFormat.DATAFRAME)
            as_json = client.read(["TAG1"], start=START, end=END, output=OutputFormat.JSON)

        assert isinstance(as_df, pd.DataFrame)
        assert isinstance(as_json, list)
        assert len(mock_api.calls) == 2

    @respx.mock
    def test_each_output_format_cached_separately(self, mock_api):
        """Repeating each format after both are cached hits the cache."""
        _mock_sql(mock_api)
        with _client() as client:
            for _ in range(2):
                assert isinstance(
                    client.read(["TAG1"], start=START, end=END, output=OutputFormat.JSON), list
                )
                assert isinstance(
                    client.read(["TAG1"], start=START, end=END, output=OutputFormat.DATAFRAME),
                    pd.DataFrame,
                )

        assert len(mock_api.calls) == 2

    @respx.mock
    def test_different_limit_not_shared(self, mock_api):
        """Reads with different limits are cached separately."""
        _mock_sql(mock_api)
        with _client() as client:
            client.read(["TAG1"], start=START, end=END, limit=10)
            client.read(["TAG1"], start=START, end=END, limit=100_000)
            client.read(["TAG1"], start=START, end=END, limit=10)

        assert len(mock_api.calls) == 2

    @respx.mock
    def test_different_include_not_shared(self, mock_api):
        """Reads with different include fields are cached separately."""
        mock_api.post(f"{BASE_URL}/SQL").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"ts": "2025-01-01T00:00:00Z", "name": "TAG1", "value": 1.0, "status": 0},
                    {"ts": "2025-01-01T01:00:00Z", "name": "TAG1", "value": 2.0, "status": 1},
                ],
            )
        )
        with _client() as client:
            plain = client.read(["TAG1"], start=START, end=END, output=OutputFormat.DATAFRAME)
            with_status = client.read(
                ["TAG1"],
                start=START,
                end=END,
                include=IncludeFields.STATUS,
                output=OutputFormat.DATAFRAME,
            )

        assert isinstance(plain, pd.DataFrame)
        assert isinstance(with_status, pd.DataFrame)
        assert "TAG1_status" not in plain.columns
        assert with_status["TAG1_status"].tolist() == [0, 1]
        assert len(mock_api.calls) == 2

    @respx.mock
    def test_different_interval_not_shared(self, mock_api):
        """Aggregate reads with different intervals are cached separately."""
        mock_api.post(f"{BASE_URL}/SQL").mock(
            return_value=httpx.Response(
                200,
                json=[{"ts": "2025-01-01T01:00:00Z", "name": "TAG1", "avg": 10.0}],
            )
        )
        with _client() as client:
            client.read(["TAG1"], start=START, end=END, read_type=ReaderType.AVG, interval=600)
            client.read(["TAG1"], start=START, end=END, read_type=ReaderType.AVG, interval=3600)
            client.read(["TAG1"], start=START, end=END, read_type=ReaderType.AVG, interval=600)

        assert len(mock_api.calls) == 2

    @respx.mock
    def test_tag_order_not_shared(self, mock_api):
        """Tag order sets column order, so it is part of the key."""
        _mock_sql(mock_api)
        with _client() as client:
            df_ab = client.read(
                ["TAG1", "TAG2"], start=START, end=END, output=OutputFormat.DATAFRAME
            )
            df_ba = client.read(
                ["TAG2", "TAG1"], start=START, end=END, output=OutputFormat.DATAFRAME
            )

        assert isinstance(df_ab, pd.DataFrame)
        assert isinstance(df_ba, pd.DataFrame)
        assert list(df_ab.columns) == ["TAG1", "TAG2"]
        assert list(df_ba.columns) == ["TAG2", "TAG1"]
        assert len(mock_api.calls) == 2

    @respx.mock
    def test_same_tags_same_order_hit(self, mock_api):
        """Repeating a multi-tag read in the same order hits the cache."""
        _mock_sql(mock_api)
        with _client() as client:
            first = client.read(["TAG1", "TAG2"], start=START, end=END)
            second = client.read(["TAG1", "TAG2"], start=START, end=END)

        assert first == second
        assert len(mock_api.calls) == 1

    @respx.mock
    def test_equivalent_start_end_strings_hit(self, mock_api):
        """Start/end strings for the same server time share one entry."""
        _mock_sql(mock_api)
        with _client(server_timezone="UTC") as client:
            client.read(["TAG1"], start=START, end=END)
            client.read(
                ["TAG1"], start="2025-01-01T01:00:00+01:00", end="2025-01-01T03:00:00+01:00"
            )

        assert len(mock_api.calls) == 1


class TestSharedCacheKey:
    """Clients sharing one AspenCache must not serve each other's results."""

    @respx.mock
    def test_same_settings_share_entries(self, mock_api):
        """Clients with identical settings still benefit from a shared cache."""
        _mock_sql(mock_api)
        shared = AspenCache()
        with _client(cache=shared) as c1, _client(cache=shared) as c2:
            r1 = c1.read(["TAG1"], start=START, end=END)
            r2 = c2.read(["TAG1"], start=START, end=END)

        assert r1 == r2
        assert len(mock_api.calls) == 1

    @respx.mock
    def test_different_datasource_not_shared(self, mock_api):
        """Clients on different datasources keep separate read entries."""
        _mock_sql(mock_api)
        shared = AspenCache()
        with _client(cache=shared) as c1, _client(cache=shared, datasource="IP21_B") as c2:
            c1.read(["TAG1"], start=START, end=END)
            c2.read(["TAG1"], start=START, end=END)

        assert len(mock_api.calls) == 2

    @respx.mock
    def test_different_base_url_not_shared(self, mock_api):
        """Clients on different servers keep separate read entries."""
        route_a = _mock_sql(mock_api)
        route_b = _mock_sql(mock_api, OTHER_BASE_URL)
        shared = AspenCache()
        with _client(cache=shared) as c1, _client(cache=shared, base_url=OTHER_BASE_URL) as c2:
            c1.read(["TAG1"], start=START, end=END)
            c2.read(["TAG1"], start=START, end=END)

        assert route_a.call_count == 1
        assert route_b.call_count == 1

    @respx.mock
    def test_trailing_slash_base_url_shared(self, mock_api):
        """A trailing slash on base_url does not split the cache."""
        _mock_sql(mock_api)
        shared = AspenCache()
        with _client(cache=shared) as c1, _client(cache=shared, base_url=BASE_URL + "/") as c2:
            c1.read(["TAG1"], start=START, end=END)
            c2.read(["TAG1"], start=START, end=END)

        assert len(mock_api.calls) == 1

    @respx.mock
    def test_different_server_timezone_not_shared(self, mock_api):
        """Results localized to one time zone are not served to another."""
        _mock_sql(mock_api)
        shared = AspenCache()
        c_utc = _client(cache=shared, server_timezone="UTC")
        c_berlin = _client(cache=shared, server_timezone="Europe/Berlin")
        with c_utc, c_berlin:
            df_utc = c_utc.read(["TAG1"], start=START, end=END, output=OutputFormat.DATAFRAME)
            df_berlin = c_berlin.read(["TAG1"], start=START, end=END, output=OutputFormat.DATAFRAME)

        assert isinstance(df_utc, pd.DataFrame)
        assert isinstance(df_berlin, pd.DataFrame)
        assert isinstance(df_utc.index, pd.DatetimeIndex)
        assert isinstance(df_berlin.index, pd.DatetimeIndex)
        assert str(df_utc.index.tz) == "UTC"
        assert str(df_berlin.index.tz) == "Europe/Berlin"
        assert len(mock_api.calls) == 2

    @respx.mock
    def test_naive_and_aware_clients_not_shared(self, mock_api):
        """A client without server_timezone does not get tz-aware cached results."""
        _mock_sql(mock_api)
        shared = AspenCache()
        c_aware = _client(cache=shared, server_timezone="UTC")
        c_naive = _client(cache=shared)
        with c_aware, c_naive:
            df_aware = c_aware.read(["TAG1"], start=START, end=END, output=OutputFormat.DATAFRAME)
            df_naive = c_naive.read(["TAG1"], start=START, end=END, output=OutputFormat.DATAFRAME)

        assert isinstance(df_aware, pd.DataFrame)
        assert isinstance(df_naive, pd.DataFrame)
        assert isinstance(df_aware.index, pd.DatetimeIndex)
        assert isinstance(df_naive.index, pd.DatetimeIndex)
        assert df_aware.index.tz is not None
        assert df_naive.index.tz is None
        assert len(mock_api.calls) == 2

    @respx.mock
    def test_search_different_datasource_not_shared(self, mock_api):
        """Search results are kept per datasource."""
        route = _mock_browse(mock_api)
        shared = AspenCache()
        with _client(cache=shared) as c1, _client(cache=shared, datasource="IP21_B") as c2:
            c1.search(tag="TEMP*")
            c2.search(tag="TEMP*")

        assert route.call_count == 2
        assert route.calls[0].request.url.params["dataSource"] == "IP21"
        assert route.calls[1].request.url.params["dataSource"] == "IP21_B"

    @respx.mock
    def test_search_different_base_url_not_shared(self, mock_api):
        """Search results are kept per server."""
        route_a = _mock_browse(mock_api)
        route_b = _mock_browse(mock_api, OTHER_BASE_URL)
        shared = AspenCache()
        with _client(cache=shared) as c1, _client(cache=shared, base_url=OTHER_BASE_URL) as c2:
            c1.search(tag="TEMP*")
            c2.search(tag="TEMP*")

        assert route_a.call_count == 1
        assert route_b.call_count == 1

    @respx.mock
    def test_search_same_settings_share_entries(self, mock_api):
        """Clients with identical settings share search entries."""
        route = _mock_browse(mock_api)
        shared = AspenCache()
        with _client(cache=shared) as c1, _client(cache=shared) as c2:
            assert c1.search(tag="TEMP*") == c2.search(tag="TEMP*")

        assert route.call_count == 1

    @respx.mock
    def test_search_different_server_timezone_shared(self, mock_api):
        """Search results do not depend on the time zone, so they are shared."""
        route = _mock_browse(mock_api)
        shared = AspenCache()
        c_utc = _client(cache=shared, server_timezone="UTC")
        c_berlin = _client(cache=shared, server_timezone="Europe/Berlin")
        with c_utc, c_berlin:
            assert c_utc.search(tag="TEMP*") == c_berlin.search(tag="TEMP*")

        assert route.call_count == 1


class TestSearchCacheKey:
    """Every search-only argument that changes the result must be part of the key."""

    @respx.mock
    def test_different_include_not_shared(self, mock_api):
        """Names-only and with-description searches are cached separately."""
        route = _mock_browse(mock_api)
        with _client() as client:
            names = client.search(tag="TEMP*")
            described = client.search(tag="TEMP*", include=IncludeFields.DESCRIPTION)

        assert names == ["TEMP_101", "TEMP_102"]
        assert isinstance(described, list)
        assert isinstance(described[0], dict)
        assert route.call_count == 2

    @respx.mock
    def test_different_limit_not_shared(self, mock_api):
        """Searches with different limits are cached separately."""
        route = _mock_browse(mock_api)
        with _client() as client:
            one = client.search(tag="TEMP*", limit=1)
            both = client.search(tag="TEMP*", limit=10)

        assert len(one) == 1
        assert len(both) == 2
        assert route.call_count == 2

    @respx.mock
    def test_different_pattern_not_shared(self, mock_api):
        """Searches with different patterns are cached separately."""
        route = _mock_browse(mock_api)
        with _client() as client:
            client.search(tag="TEMP*")
            client.search(tag="PRES*")

        assert route.call_count == 2


class TestReadCacheKeyParams:
    """Unit tests for AspenClient._read_cache_key_params."""

    BASE_PARAMS: ClassVar[dict[str, Any]] = {
        "tags": ["TAG1", "TAG2"],
        "start": "2025-01-01T00:00:00",
        "end": "2025-01-01T02:00:00",
        "interval": None,
        "read_type": ReaderType.INT,
        "include_status": False,
        "with_description": False,
        "limit": 100_000,
        "as_df": False,
    }

    @staticmethod
    def _key(client, **overrides):
        params = {**TestReadCacheKeyParams.BASE_PARAMS, **overrides}
        cache = AspenCache()
        return cache._generate_key("read_historical", **client._read_cache_key_params(**params))

    def test_same_params_same_key(self):
        with _client() as client:
            assert self._key(client) == self._key(client)

    @pytest.mark.parametrize(
        "override",
        [
            pytest.param({"tags": ["TAG1"]}, id="fewer_tags"),
            pytest.param({"tags": ["TAG2", "TAG1"]}, id="reordered_tags"),
            pytest.param({"start": "2025-01-01T00:30:00"}, id="start"),
            pytest.param({"end": "2025-01-01T03:00:00"}, id="end"),
            pytest.param({"interval": 600}, id="interval"),
            pytest.param({"read_type": ReaderType.RAW}, id="read_type"),
            pytest.param({"include_status": True}, id="include_status"),
            pytest.param({"with_description": True}, id="with_description"),
            pytest.param({"limit": 10}, id="limit"),
            pytest.param({"as_df": True}, id="as_df"),
        ],
    )
    def test_each_argument_changes_key(self, override):
        with _client() as client:
            assert self._key(client, **override) != self._key(client)

    @pytest.mark.parametrize(
        "client_kwargs",
        [
            {"base_url": OTHER_BASE_URL},
            {"datasource": "IP21_B"},
            {"datasource": None},
            {"server_timezone": "UTC"},
            {"server_timezone": "Europe/Berlin"},
        ],
        ids=lambda kw: f"{next(iter(kw))}={next(iter(kw.values()))}",
    )
    def test_client_settings_change_key(self, client_kwargs):
        with _client() as default, _client(**client_kwargs) as other:
            assert self._key(other) != self._key(default)

    def test_tzinfo_and_name_give_same_key(self):
        """A ZoneInfo object and its name identify the same server time zone."""
        from zoneinfo import ZoneInfo

        by_name = _client(server_timezone="Europe/Berlin")
        by_obj = _client(server_timezone=ZoneInfo("Europe/Berlin"))
        with by_name, by_obj:
            assert self._key(by_name) == self._key(by_obj)

    def test_includes_every_read_argument(self):
        """Guard against new read() arguments being left out of the key."""
        with _client() as client:
            params = client._read_cache_key_params(**self.BASE_PARAMS)
        assert set(self.BASE_PARAMS) <= set(params)
        assert {"base_url", "datasource", "server_timezone"} <= set(params)


class TestCachedResultsAreCopies:
    """Modifying a returned result must not change what later cache hits return."""

    @respx.mock
    def test_mutating_first_dataframe_does_not_change_cache(self, mock_api):
        _mock_sql(mock_api)
        with _client() as client:
            df = client.read(["TAG1"], start=START, end=END, output=OutputFormat.DATAFRAME)
            assert isinstance(df, pd.DataFrame)
            df["TAG1"] = 999
            again = client.read(["TAG1"], start=START, end=END, output=OutputFormat.DATAFRAME)

        assert isinstance(again, pd.DataFrame)
        assert again["TAG1"].tolist() == [10.5, 11.5]
        assert len(mock_api.calls) == 1

    @respx.mock
    def test_mutating_cache_hit_dataframe_does_not_change_cache(self, mock_api):
        _mock_sql(mock_api)
        with _client() as client:
            client.read(["TAG1"], start=START, end=END, output=OutputFormat.DATAFRAME)
            hit = client.read(["TAG1"], start=START, end=END, output=OutputFormat.DATAFRAME)
            assert isinstance(hit, pd.DataFrame)
            del hit["TAG1"]  # modify the returned frame in place
            again = client.read(["TAG1"], start=START, end=END, output=OutputFormat.DATAFRAME)

        assert isinstance(again, pd.DataFrame)
        assert list(again.columns) == ["TAG1"]
        assert len(mock_api.calls) == 1

    @respx.mock
    def test_mutating_json_records_does_not_change_cache(self, mock_api):
        _mock_sql(mock_api)
        with _client() as client:
            records = client.read(["TAG1"], start=START, end=END)
            assert isinstance(records, list)
            expected = [dict(r) for r in records]
            records[0]["value"] = 999
            records.clear()
            again = client.read(["TAG1"], start=START, end=END)

        assert again == expected
        assert len(mock_api.calls) == 1

    @respx.mock
    def test_mutating_search_results_does_not_change_cache(self, mock_api):
        _mock_browse(mock_api)
        with _client() as client:
            names = client.search(tag="TEMP*")
            assert isinstance(names, list)
            names.clear()
            again = client.search(tag="TEMP*")

        assert again == ["TEMP_101", "TEMP_102"]
        assert len(mock_api.calls) == 1


class TestInvalidateCache:
    """AspenClient.invalidate_cache() removes matching read entries."""

    @staticmethod
    def _fill(client, *tag_lists, start=START, end=END):
        for tags in tag_lists:
            client.read(tags, start=start, end=end)

    @respx.mock
    def test_by_tag(self, mock_api):
        _mock_sql(mock_api)
        with _client() as client:
            self._fill(client, ["TAG1"], ["TAG2"])
            assert client.invalidate_cache(tags=["TAG1"]) == 1
            self._fill(client, ["TAG1"], ["TAG2"])

        # TAG1 is fetched again, TAG2 is still cached
        assert len(mock_api.calls) == 3

    @respx.mock
    @pytest.mark.parametrize(("cached", "invalidated"), [("tag1", "TAG1"), ("TAG1", "Tag1")])
    def test_tag_case_ignored(self, mock_api, cached, invalidated):
        """Tag names are case-insensitive in IP.21, so also when invalidating."""
        _mock_sql(mock_api)
        with _client() as client:
            self._fill(client, [cached], ["TAG2"])
            assert client.invalidate_cache(tags=[invalidated]) == 1

    @respx.mock
    def test_entry_with_any_matching_tag_removed(self, mock_api):
        _mock_sql(mock_api)
        with _client() as client:
            self._fill(client, ["TAG1", "TAG2"])
            assert client.invalidate_cache(tags=["TAG2"]) == 1

    @respx.mock
    def test_unknown_tag_removes_nothing(self, mock_api):
        _mock_sql(mock_api)
        with _client() as client:
            self._fill(client, ["TAG1"])
            assert client.invalidate_cache(tags=["NOPE"]) == 0
            self._fill(client, ["TAG1"])

        assert len(mock_api.calls) == 1

    @respx.mock
    def test_all_variants_of_a_read_removed(self, mock_api):
        """Entries differing only by output format or limit are all removed."""
        _mock_sql(mock_api)
        with _client() as client:
            client.read(["TAG1"], start=START, end=END)
            client.read(["TAG1"], start=START, end=END, output=OutputFormat.DATAFRAME)
            client.read(["TAG1"], start=START, end=END, limit=1)
            assert client.invalidate_cache(tags=["TAG1"]) == 3

    @respx.mock
    def test_by_time_range(self, mock_api):
        _mock_sql(mock_api)
        with _client() as client:
            self._fill(client, ["TAG1"])
            self._fill(client, ["TAG1"], start="2025-01-02 00:00:00", end="2025-01-02 02:00:00")
            assert client.invalidate_cache(tags=["TAG1"], start=START, end=END) == 1
            assert client.invalidate_cache(tags=["TAG1"]) == 1

    @respx.mock
    def test_start_only(self, mock_api):
        _mock_sql(mock_api)
        with _client() as client:
            self._fill(client, ["TAG1"])
            self._fill(client, ["TAG1"], end="2025-01-01 03:00:00")
            self._fill(client, ["TAG1"], start="2025-01-01 01:00:00")
            assert client.invalidate_cache(start=START) == 2

    @respx.mock
    def test_time_range_without_tags(self, mock_api):
        _mock_sql(mock_api)
        with _client() as client:
            self._fill(client, ["TAG1"], ["TAG2"])
            assert client.invalidate_cache(start=START, end=END) == 2

    @respx.mock
    def test_equivalent_timestamp_strings_match(self, mock_api):
        """Start/end are compared as server times, not as raw strings."""
        _mock_sql(mock_api)
        with _client(server_timezone="UTC") as client:
            self._fill(client, ["TAG1"])
            count = client.invalidate_cache(
                tags=["TAG1"],
                start="2025-01-01T01:00:00+01:00",
                end="2025-01-01T03:00:00+01:00",
            )

        assert count == 1

    @respx.mock
    def test_search_entries_kept(self, mock_api):
        _mock_sql(mock_api)
        route = _mock_browse(mock_api)
        with _client() as client:
            client.search(tag="TEMP*")
            self._fill(client, ["TAG1"])
            assert client.invalidate_cache(tags=["TAG1"]) == 1
            client.search(tag="TEMP*")

        assert route.call_count == 1

    @respx.mock
    def test_other_clients_entries_kept(self, mock_api):
        """Invalidating on one client leaves other datasources' entries in a shared cache."""
        _mock_sql(mock_api)
        shared = AspenCache()
        with _client(cache=shared) as c1, _client(cache=shared, datasource="IP21_B") as c2:
            self._fill(c1, ["TAG1"])
            self._fill(c2, ["TAG1"])
            assert c1.invalidate_cache(tags=["TAG1"]) == 1
            self._fill(c2, ["TAG1"])

        assert len(mock_api.calls) == 2

    def test_entries_not_written_by_read_ignored(self):
        """Entries stored directly on a shared cache don't break tag matching."""
        shared = AspenCache()
        shared.set("read_historical", "raw", tags=["TAG1"])
        with _client(cache=shared) as client:
            assert client.invalidate_cache(tags=["TAG1"]) == 0

        assert shared.get_stats()["size"] == 1
