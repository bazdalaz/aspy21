"""Main client for interacting with Aspen InfoPlus.21 REST API."""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Literal, overload

import httpx
import pandas as pd

from .cache import AspenCache, CacheConfig
from .errors import AspenBrowseError, raise_for_sql_error
from .models import IncludeFields, OutputFormat, ReaderType
from .query_builder import SqlSearchQueryBuilder
from .retry import send
from .utils import check_timezone, localize_server_index, server_now, to_server_time

if TYPE_CHECKING:
    from datetime import tzinfo

    from httpx import Auth
    from typing_extensions import Self

logger = logging.getLogger(__name__)

# Cache operations used for read() results (see _determine_cache_operation)
DEFAULT_TIMEOUT = 30.0  # seconds

_READ_CACHE_OPERATIONS = ("read_historical", "read_aggregates", "read_snapshot")


def configure_logging(level: str | None = None) -> None:
    """Configure logging level for aspy21 library.

    Applies to every aspy21 module (client, readers, retries, cache), not only the client.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
               If None, reads from ASPEN_LOG_LEVEL environment variable.
               Defaults to WARNING if not set.
    """
    if level is None:
        level = os.getenv("ASPEN_LOG_LEVEL", "WARNING")

    numeric_level = getattr(logging, level.upper(), logging.WARNING)
    package_logger = logging.getLogger("aspy21")
    package_logger.setLevel(numeric_level)

    # Only add handler if logger doesn't have one already
    if not package_logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        package_logger.addHandler(handler)


class AspenClient:
    """Client for Aspen InfoPlus.21 REST API.

    Provides methods to read historical and real-time process data from
    Aspen IP.21 historian via REST API with automatic batching, retries,
    and pandas DataFrame output.

    Supports context manager protocol for automatic resource cleanup.
    """

    def __init__(
        self,
        base_url: str,
        *,
        auth: Auth | tuple[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        verify_ssl: bool = True,
        datasource: str | None = None,
        http_client: httpx.Client | None = None,
        cache: AspenCache | CacheConfig | bool | None = None,
        server_timezone: str | tzinfo | None = None,
        retries: int = 2,
    ) -> None:
        """Initialize the Aspen client.

        Args:
            base_url: URL of the ProcessData REST API, ending in AtProcessDataREST.dll,
                e.g. "http://server/ProcessData/AtProcessDataREST.dll"
            auth: Authentication as (username, password) tuple or httpx Auth object.
                  If None, no authentication is used.
            timeout: Request timeout in seconds (default: 30.0)
            verify_ssl: Whether to verify SSL certificates (default: True)
            datasource: IP.21 datasource name, e.g. "IP21". Required: read() and
                search() raise ValueError without it.
            http_client: Optional httpx.Client instance. If None, creates a new client.
                        Useful for dependency injection and testing. When given,
                        timeout, verify_ssl and auth are not applied (a warning is
                        logged if they are passed); configure them on the httpx.Client.
            cache: Cache configuration:
                  - None: No caching (default)
                  - True: Enable caching with default config
                  - CacheConfig: Enable caching with custom config
                  - AspenCache: Use existing cache instance
            server_timezone: Time zone of the IP.21 server, e.g. "Europe/Berlin".
                IP.21 reads and returns timestamps in the server's local time.
                - None: Return naive server-local timestamps (default). Timezone-aware
                  start/end values are converted to this machine's local zone.
                - Zone name or tzinfo: Return timestamps in that zone, and convert
                  timezone-aware start/end values to it.
            retries: How many times to repeat a request after a transient failure
                (default: 2, so up to 3 attempts; 0 disables retries). Connection errors,
                connect timeouts and HTTP 429/502/503/504 are retried with exponential
                backoff (0.5s, 1s, ... up to 8s) or the server's Retry-After. Read
                timeouts, other HTTP errors and SQL errors are not retried.

        Raises:
            ValueError: If retries is negative or server_timezone is not a known zone
            TypeError: If cache is not None, a bool, a CacheConfig or an AspenCache

        Example:
            Using context manager with authentication:
                >>> with AspenClient(
                ...     "http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
                ...     auth=("user", "pass"),
                ...     datasource="IP21",
                ... ) as client:
                ...     data = client.read(
                ...         ["TAG1"], start="2025-01-01 00:00:00", end="2025-01-02 00:00:00"
                ...     )

            Searching for tags:
                >>> with AspenClient(
                ...     "http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
                ...     datasource="IP21",
                ... ) as client:
                ...     tags = client.search("TEMP*")

            With custom HTTP client (timeout, verify_ssl and auth are set on it):
                >>> http = httpx.Client(timeout=60.0, verify=False, auth=("user", "pass"))
                >>> aspen = AspenClient(
                ...     "http://aspen.example.com/ProcessData/AtProcessDataREST.dll",
                ...     datasource="IP21",
                ...     http_client=http,
                ... )
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.datasource = datasource or ""  # Empty string = use server default
        self.auth = auth
        check_timezone(server_timezone)
        self.server_timezone = server_timezone
        if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
            raise ValueError(f"retries must be a non-negative integer, got {retries!r}")
        self.retries = retries

        # Support dependency injection of HTTP client
        self._owns_client = http_client is None
        if http_client is None:
            self._client = httpx.Client(timeout=timeout, verify=verify_ssl, auth=auth)
        else:
            self._client = http_client
            ignored = [
                name
                for name, passed in (
                    ("auth", auth is not None),
                    ("timeout", timeout != DEFAULT_TIMEOUT),
                    ("verify_ssl", verify_ssl is not True),
                )
                if passed
            ]
            if ignored:
                logger.warning(
                    f"{', '.join(ignored)} not applied to the provided http_client; "
                    "set them on the httpx.Client instead"
                )

        # Initialize cache
        if cache is None:
            self._cache: AspenCache | None = None
        elif isinstance(cache, bool):
            self._cache = AspenCache() if cache else None
        elif isinstance(cache, CacheConfig):
            self._cache = AspenCache(cache)
        elif isinstance(cache, AspenCache):
            self._cache = cache
        else:
            raise TypeError(
                f"cache must be None, bool, CacheConfig, or AspenCache, got {type(cache)}"
            )

        # Initialize reader strategies
        from .readers import (
            AggregatesReader,
            SnapshotReader,
            SqlHistoryReader,
        )

        reader_args = (self.base_url, self.datasource, self._client, server_timezone)
        self._readers = [
            SnapshotReader(*reader_args, retries=retries),
            AggregatesReader(*reader_args, retries=retries),  # Check aggregates before history
            SqlHistoryReader(*reader_args, retries=retries),
        ]

        logger.info(f"Initialized AspenClient for {self.base_url}")
        if self._owns_client:
            http_config = f"timeout={timeout}s, verify_ssl={verify_ssl}"
        else:
            # timeout, verify_ssl and auth arguments are not applied to a provided client
            http_config = f"provided http_client (timeout={self._client.timeout.read}s)"
        logger.debug(f"Config: {http_config}, datasource={datasource}, retries={retries}")
        if self._cache:
            logger.info(f"Cache enabled: {self._cache.get_stats()}")

    def __enter__(self) -> Self:
        """Enter context manager.

        Returns:
            self for use in with statement
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager and close connection.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred
        """
        self.close()

    def close(self) -> None:
        """Close the HTTP client connection.

        Note: Only closes the client if it was created by AspenClient.
        If a custom http_client was provided during initialization, it will not be closed.
        """
        if self._owns_client:
            self._client.close()

    def _is_historical_data(self, end: str | None) -> bool:
        """Check if the requested data is historical (in the past).

        Only historical data should be cached with long TTL, as it's immutable.
        Current/future data should have short TTL or no caching.

        Args:
            end: End timestamp string

        Returns:
            True if data is definitely in the past, False otherwise
        """
        if end is None:
            return False

        try:
            end_dt = to_server_time(end, self.server_timezone)
            # Add 1 minute buffer to account for clock skew
            return end_dt < (server_now(self.server_timezone) - pd.Timedelta(minutes=1))
        except (ValueError, TypeError):
            # If we can't parse, assume not historical to be safe
            return False

    def _determine_cache_operation(
        self, read_type: ReaderType, start: str | None, end: str | None
    ) -> str:
        """Determine cache operation type based on read parameters.

        Args:
            read_type: Type of read operation
            start: Start timestamp
            end: End timestamp

        Returns:
            Cache operation string for TTL lookup
        """
        if start is None and end is None:
            return "read_snapshot"

        if read_type in (ReaderType.AVG, ReaderType.MIN, ReaderType.MAX, ReaderType.RNG):
            return "read_aggregates"

        return "read_historical"

    def _client_cache_identity(self) -> dict[str, str]:
        """Return the server and datasource that cached results come from.

        A cache can be shared across clients, so keys must tell servers and
        datasources apart.
        """
        return {"base_url": self.base_url, "datasource": self.datasource}

    def _read_cache_key_params(
        self,
        *,
        tags: list[str],
        start: str | None,
        end: str | None,
        interval: int | None,
        read_type: ReaderType,
        include_status: bool,
        with_description: bool,
        limit: int,
        as_df: bool,
    ) -> dict:
        """Build the cache key parameters for a read() call.

        Every argument that changes the returned result must be part of the key.
        """
        return {
            # Serialized so tag order (which sets column order) is part of the key
            "tags": json.dumps(tags),
            "start": start,
            "end": end,
            "interval": interval,
            "read_type": read_type.value,
            "include_status": include_status,
            "with_description": with_description,
            "limit": limit,
            "as_df": as_df,
            # Read results are localized to the server time zone
            "server_timezone": str(self.server_timezone) if self.server_timezone else None,
            **self._client_cache_identity(),
        }

    def get_cache_stats(self) -> dict | None:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats (hits, misses, hit_rate, size) or None if cache disabled
        """
        return self._cache.get_stats() if self._cache else None

    def clear_cache(self) -> int:
        """Clear all cached entries.

        Returns:
            Number of entries cleared, or 0 if cache disabled
        """
        if self._cache:
            return self._cache.invalidate()
        return 0

    def invalidate_cache(
        self, tags: list[str] | None = None, start: str | None = None, end: str | None = None
    ) -> int:
        """Invalidate specific cache entries.

        With no arguments the whole cache is cleared. Otherwise cached read results
        from this client's server and datasource are removed when they match every
        argument given: any of their tags is in ``tags``, and their start and end
        equal ``start`` and ``end``. Start and end are compared as server times, so
        any string accepted by read() for the same instant matches.

        Args:
            tags: Tag names to invalidate. If None, entries for any tags match.
            start: Start timestamp to match. If None, any start matches.
            end: End timestamp to match. If None, any end matches.

        Returns:
            Number of entries invalidated
        """
        if not self._cache:
            return 0

        if tags is None and start is None and end is None:
            return self._cache.invalidate()

        identity = self._client_cache_identity()
        tag_set = set(tags) if tags is not None else None
        start = to_server_time(start, self.server_timezone).isoformat() if start else None
        end = to_server_time(end, self.server_timezone).isoformat() if end else None

        def matches(operation: str, params: dict) -> bool:
            if operation not in _READ_CACHE_OPERATIONS:
                return False
            if any(params.get(k) != v for k, v in identity.items()):
                return False
            if tag_set is not None:
                cached_tags = params.get("tags")
                if not isinstance(cached_tags, str):
                    return False
                if not tag_set.intersection(json.loads(cached_tags)):
                    return False
            if start is not None and params.get("start") != start:
                return False
            return end is None or params.get("end") == end

        return self._cache.invalidate_where(matches)

    @overload
    def read(
        self,
        tags: list[str],
        *,
        start: str | None = None,
        end: str | None = None,
        interval: int | None = None,
        read_type: ReaderType = ReaderType.INT,
        include: IncludeFields = IncludeFields.NONE,
        limit: int = 100_000,
        output: Literal[OutputFormat.DATAFRAME],
    ) -> pd.DataFrame: ...

    @overload
    def read(
        self,
        tags: list[str],
        *,
        start: str | None = None,
        end: str | None = None,
        interval: int | None = None,
        read_type: ReaderType = ReaderType.INT,
        include: IncludeFields = IncludeFields.NONE,
        limit: int = 100_000,
        output: Literal[OutputFormat.JSON] = OutputFormat.JSON,
    ) -> list[dict]: ...

    @overload
    def read(
        self,
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

    def read(
        self,
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
        """Read process data for multiple tags.

        Args:
            tags: List of tag names to retrieve. Case does not matter, as in IP.21; results
                use the names as given here.
            start: Start timestamp (ISO format or compatible string). If start and end are
                both omitted, the current values are read (SNAPSHOT). Naive values are server
                local time; timezone-aware values are converted (see server_timezone).
            end: End timestamp (ISO format or compatible string). Defaults to the current
                time when only start is given.
            interval: Interval in seconds. For INT reads, the spacing of interpolated values;
                for AVG, MIN, MAX and RNG, the length of each aggregate period (without it,
                one value covers start to end). IP.21 stamps each aggregate at the end of
                its period. Leave it unset for RAW and SNAPSHOT reads.
            read_type: Type of data retrieval (default: INT)
                - RAW: Values as stored in the historian
                - INT: Interpolated values
                - SNAPSHOT: Current values (also used when start and end are omitted)
                - AVG, MIN, MAX, RNG: Aggregates (average, minimum, maximum, max - min)
            include: Field inclusion options (default: NONE)
                - NONE: Include only timestamp and value
                - STATUS: Include status field
                - DESCRIPTION: Include description field
                - ALL: Include both status and description
            limit: Maximum number of rows to return per tag (default: 100000). A tag that
                reaches it logs a warning: its values after the last returned row are not
                read. For several tags, tags cut short by the shared query are read again
                one at a time.
            output: Output format (default: JSON)
                - JSON: Return as list of dictionaries
                - DATAFRAME: Return as pandas DataFrame

        Returns:
            Timestamps are naive server-local times, or timezone-aware when server_timezone
            is set.

            If output=DATAFRAME: pandas DataFrame indexed by time ("time"), sorted, with one
                column per tag that returned data. Tags without a value at a timestamp are
                NaN there. With include=STATUS or ALL, a "<tag>_status" column follows each
                tag; with DESCRIPTION or ALL, a "<tag>_description" column. When a tag has
                several values at one timestamp (RAW reads), each gets its own row, so the
                index can repeat. With DESCRIPTION or ALL, df.attrs["tag_descriptions"]
                maps tag names to descriptions.
            If output=JSON: List of dictionaries, one per value, sorted by time:
                - timestamp: ISO format timestamp string
                - tag: Tag name
                - value: Tag value (int, float or str)
                - description: Tag description (when include=DESCRIPTION or ALL)
                - status: Status code (when include=STATUS or ALL)
            An empty DataFrame or list when no tag returned data.

        Raises:
            ValueError: If tags is empty or datasource is not set
            AspenSqlError: If IP.21 rejects the query (an AspenError, which is a ValueError)
            httpx.HTTPStatusError: For an HTTP error response, after any retries
            httpx.RequestError: For a connection failure or timeout, after any retries

        Example:
            >>> # JSON output (default)
            >>> data = client.read(
            ...     ["TEMP_201"],
            ...     start="2025-01-01 00:00:00",
            ...     end="2025-01-01 01:00:00",
            ... )
            >>> # Returns: [
            >>> #   {"timestamp": "2025-01-01T00:00:00", "tag": "TEMP_201", "value": 25.5},
            >>> #   ...
            >>> # ]

            >>> # 10-minute averages as a DataFrame with descriptions
            >>> df = client.read(
            ...     ["TEMP_201", "PRESS_201.PV"],
            ...     start="2025-01-01 00:00:00",
            ...     end="2025-01-01 01:00:00",
            ...     interval=600,
            ...     read_type=ReaderType.AVG,
            ...     include=IncludeFields.DESCRIPTION,
            ...     output=OutputFormat.DATAFRAME,
            ... )
        """
        from .readers import DataFormatter

        if not tags:
            raise ValueError("At least one tag is required")

        # Convert include enum to boolean flags for internal use
        include_status = include in (IncludeFields.STATUS, IncludeFields.ALL)
        with_description = include in (IncludeFields.DESCRIPTION, IncludeFields.ALL)

        # Convert output enum to boolean for internal use
        as_df = output == OutputFormat.DATAFRAME

        # Auto-detect SNAPSHOT reads when start/end not provided
        effective_read_type = read_type
        if start is None and end is None:
            if effective_read_type != ReaderType.SNAPSHOT:
                logger.info(
                    "No start/end provided; defaulting to SNAPSHOT read for %d tag(s)",
                    len(tags),
                )
            effective_read_type = ReaderType.SNAPSHOT
        elif start is not None and end is None:
            # If start provided but end omitted, use current time
            end = server_now(self.server_timezone).isoformat()
            logger.debug(f"End time not provided, using current time: {end}")

        # IP.21 interprets query times as server local time
        if start is not None:
            start = to_server_time(start, self.server_timezone).isoformat()
        if end is not None:
            end = to_server_time(end, self.server_timezone).isoformat()

        logger.debug(f"Tags: {tags}")
        logger.debug(f"Reader type: {effective_read_type.value}, Interval: {interval}")

        # Check cache before making API call (only for historical data)
        if self._cache and self._is_historical_data(end):
            cache_operation = self._determine_cache_operation(effective_read_type, start, end)
            cache_key_params = self._read_cache_key_params(
                tags=tags,
                start=start,
                end=end,
                interval=interval,
                read_type=effective_read_type,
                include_status=include_status,
                with_description=with_description,
                limit=limit,
                as_df=as_df,
            )
            cached_result = self._cache.get(cache_operation, **cache_key_params)
            if cached_result is not None:
                logger.debug(f"Cache hit for {cache_operation}")
                return cached_result

        # Require datasource for historical reads (RAW, INT, MIN, MAX, AVG, RNG)
        if start is not None and end is not None and not self.datasource:
            message = "Datasource is required for historical reads. "
            message += "Please set datasource when creating AspenClient: "
            message += "AspenClient(base_url=..., datasource='your_datasource')"
            raise ValueError(message)

        # Select appropriate reader strategy
        for reader in self._readers:
            if reader.can_handle(effective_read_type, start, end):
                frames, tag_descriptions = reader.read(
                    tags=tags,
                    start=start,
                    end=end,
                    interval=interval,
                    read_type=effective_read_type,
                    include_status=include_status,
                    max_rows=limit,
                    with_description=with_description,
                )
                break
        else:
            raise ValueError(f"No reader available for read_type={effective_read_type}")

        frames = [localize_server_index(frame, self.server_timezone) for frame in frames]

        # Format output using formatter
        result = DataFormatter.format_output(
            frames=frames,
            tags=tags,
            tag_descriptions=tag_descriptions,
            as_df=as_df,
            include_status=include_status,
            with_description=with_description,
        )

        # Cache the result if enabled
        # Only cache historical data with long TTL to avoid caching current values.
        # Empty results are not cached: they may be transient (e.g. data not yet archived).
        if self._cache and self._is_historical_data(end) and len(result) > 0:
            cache_operation = self._determine_cache_operation(effective_read_type, start, end)
            cache_key_params = self._read_cache_key_params(
                tags=tags,
                start=start,
                end=end,
                interval=interval,
                read_type=effective_read_type,
                include_status=include_status,
                with_description=with_description,
                limit=limit,
                as_df=as_df,
            )
            self._cache.set(cache_operation, result, **cache_key_params)
            logger.debug(f"Cached result for {cache_operation}")

        return result

    def _search_by_sql(
        self,
        description: str,
        tag_pattern: str = "*",
        max_results: int = 10000,
        return_desc: bool = True,
    ) -> list[dict[str, str]] | list[str]:
        """Search for tags by description using SQL endpoint.

        This is an internal method that uses the Aspen SQL endpoint to search
        by tag description (ip_description field) and optionally by tag name.
        Both filters are applied server-side in the SQL WHERE clause.

        Args:
            description: Description pattern to search for (supports * wildcards,
                        converted to SQL % wildcards)
            tag_pattern: Tag name pattern to filter by (supports * and ? wildcards,
                        converted to SQL % and _ wildcards). Use "*" for all tags.
            max_results: Maximum number of results to return (default: 10000)

        Returns:
            List of dictionaries with 'name' and 'description' keys

        Raises:
            ValueError: If datasource is not configured
        """
        if not self.datasource:
            message: str = "Datasource is required for SQL search. "
            message += "Please set datasource when creating AspenClient: "
            message += "AspenClient(base_url=..., datasource='your_datasource')"
            raise ValueError(message)

        # Build XML query for SQL endpoint
        builder = SqlSearchQueryBuilder()
        xml = builder.build(
            datasource=self.datasource,
            description=description,
            tag_pattern=tag_pattern,
            max_results=max_results,
        )

        logger.debug(f"SQL query XML: {xml}")

        sql_url = f"{self.base_url}/SQL"
        logger.info(f"SQL request: POST {sql_url}")

        try:
            response = send(
                self._client,
                "POST",
                sql_url,
                retries=self.retries,
                content=xml,
                headers={"Content-Type": "text/xml"},
            )
            logger.debug(f"Response status: {response.status_code}")

            data = response.json()
            raise_for_sql_error(data)
            logger.debug(f"SQL response type: {type(data).__name__}")

            # Parse SQL response format
            # Expected: {"data": [{"g": "...", "r": "D", "cols": [...], "rows": [{"fld": [...]}]}]}
            if "data" not in data or not isinstance(data["data"], list):
                logger.warning("Unexpected SQL response structure")
                logger.debug(f"Full response: {data}")
                return []

            data_array = data["data"]
            if not data_array or len(data_array) == 0:
                logger.info("SQL search returned 0 results")
                return []

            # Get first result set
            result_set = data_array[0]
            if not isinstance(result_set, dict):
                logger.warning("Unexpected result set structure")
                return []

            # Get rows array
            rows = result_set.get("rows", [])
            if not rows:
                logger.info("SQL search returned 0 results")
                return []

            logger.debug(f"Found {len(rows)} rows in SQL response")

            results = []
            for row in rows:
                if not isinstance(row, dict) or "fld" not in row:
                    continue

                # Extract field values: fld is array of {"i": index, "v": value}
                fields = row["fld"]
                if len(fields) < 2:
                    continue

                tag_name = fields[0].get("v", "")
                tag_desc = fields[1].get("v", "")

                # No client-side filtering - SQL WHERE clause handles name and description
                if return_desc:
                    results.append({"name": tag_name, "description": tag_desc})
                else:
                    results.append(tag_name)

            logger.info(f"Found {len(results)} matching tags via SQL")
            return results[:max_results]

        except Exception as e:
            logger.debug(f"SQL search failed: {type(e).__name__}: {e}")
            raise

    @overload
    def search(
        self,
        tag: str = "*",
        *,
        description: str | None = None,
        case_sensitive: bool = False,
        limit: int = 10_000,
        start: str,
        end: str | None = None,
        interval: int | None = None,
        read_type: ReaderType = ReaderType.INT,
        include: IncludeFields = IncludeFields.NONE,
        output: Literal[OutputFormat.DATAFRAME],
    ) -> pd.DataFrame: ...

    @overload
    def search(
        self,
        tag: str = "*",
        *,
        description: str | None = None,
        case_sensitive: bool = False,
        limit: int = 10_000,
        start: str,
        end: str | None = None,
        interval: int | None = None,
        read_type: ReaderType = ReaderType.INT,
        include: IncludeFields = IncludeFields.NONE,
        output: Literal[OutputFormat.JSON] = OutputFormat.JSON,
    ) -> list[dict]: ...

    @overload
    def search(
        self,
        tag: str = "*",
        *,
        description: str | None = None,
        case_sensitive: bool = False,
        limit: int = 10_000,
        start: None = None,
        end: str | None = None,
        interval: int | None = None,
        read_type: ReaderType = ReaderType.INT,
        include: Literal[IncludeFields.NONE, IncludeFields.STATUS] = IncludeFields.NONE,
        output: OutputFormat = OutputFormat.JSON,
    ) -> list[str]: ...

    @overload
    def search(
        self,
        tag: str = "*",
        *,
        description: str | None = None,
        case_sensitive: bool = False,
        limit: int = 10_000,
        start: None = None,
        end: str | None = None,
        interval: int | None = None,
        read_type: ReaderType = ReaderType.INT,
        include: Literal[IncludeFields.DESCRIPTION, IncludeFields.ALL],
        output: OutputFormat = OutputFormat.JSON,
    ) -> list[dict]: ...

    @overload
    def search(
        self,
        tag: str = "*",
        *,
        description: str | None = None,
        case_sensitive: bool = False,
        limit: int = 10_000,
        start: str | None = None,
        end: str | None = None,
        interval: int | None = None,
        read_type: ReaderType = ReaderType.INT,
        include: IncludeFields = IncludeFields.NONE,
        output: OutputFormat = OutputFormat.JSON,
    ) -> pd.DataFrame | list[dict] | list[str]: ...

    def search(
        self,
        tag: str = "*",
        *,
        description: str | None = None,
        case_sensitive: bool = False,
        limit: int = 10_000,
        # Read parameters (optional, triggers hybrid mode when start is provided)
        start: str | None = None,
        end: str | None = None,
        interval: int | None = None,
        read_type: ReaderType = ReaderType.INT,
        include: IncludeFields = IncludeFields.NONE,
        output: OutputFormat = OutputFormat.JSON,
    ) -> pd.DataFrame | list[dict] | list[str]:
        """Search for tags by name pattern and/or description, optionally reading their data.

        This method operates in two modes:

        1. **Search-only mode** (no start parameter):
           Searches for tags matching the pattern and returns tag metadata.

        2. **Hybrid mode** (start parameter provided):
           Searches for tags, then reads their data for the specified time range.

        Supports wildcards:
        - '*' matches any number of characters
        - '?' matches exactly one character

        When description parameter is provided, uses SQL endpoint with server-side
        filtering for both tag name and description. Otherwise uses Browse endpoint
        for tag name only.

        Args:
            tag: Tag name pattern with wildcards (e.g., "TEMP*", "?AI_10?", "*" for all tags).
                 Defaults to "*" (all tags).
            description: Description pattern to filter by (case-insensitive substring match).
                         When provided, uses SQL endpoint for server-side search.
            case_sensitive: Whether tag name matching should be case-sensitive (default: False).
                           Only applies to Browse endpoint (tag-only search).
            limit: In search-only mode: max number of tags to return (default: 10000).
                   In hybrid mode: max number of rows per tag (default: 10000).
            start: Start timestamp for data retrieval. When provided, triggers hybrid mode.
            end: End timestamp for data retrieval. If omitted, defaults to current time.
            interval: Interval in seconds for INT and aggregate reads (see read()).
            read_type: Type of data retrieval in hybrid mode (default: INT); see read().
            include: Field inclusion options (default: NONE).
                    In search-only mode, DESCRIPTION or ALL returns descriptions with
                    the tag names. In hybrid mode, the fields added to the data (see read()).
            output: Output format in hybrid mode (default: JSON).
                   - JSON: Return as list of dictionaries
                   - DATAFRAME: Return as pandas DataFrame

        Returns:
            **Search-only mode (no start):**
            - If include=NONE or STATUS: List of tag name strings
            - If include=DESCRIPTION or ALL: List of dicts with 'name' and 'description'

            **Hybrid mode (with start):**
            - If output=JSON: List of dictionaries with timestamp, tag, value, and optional fields
            - If output=DATAFRAME: pandas DataFrame with time index and tag columns
            - An empty list or DataFrame when no tags match

        Raises:
            ValueError: If datasource is not configured
            AspenBrowseError: If the Browse endpoint (tag-only search) reports an error or
                returns an unexpected response (a ValueError subclass)
            AspenSqlError: If IP.21 reports an error for a description search or the read
            httpx.HTTPStatusError: For an HTTP error response, after any retries
            httpx.RequestError: For a connection failure or timeout, after any retries

        Example:
            >>> # Search-only: Find temperature tags (returns tag names)
            >>> tag_names = client.search(tag="TEMP*")
            >>> # Returns: ["TEMP_101", "TEMP_102", ...]
            >>>
            >>> # Search-only: Get tags with descriptions
            >>> tags = client.search(tag="TEMP*", include=IncludeFields.DESCRIPTION)
            >>> # Returns: [{"name": "TEMP_101", "description": "Reactor temp"}, ...]
            >>>
            >>> # Hybrid mode: Search and read data
            >>> data = client.search(
            ...     tag="TEMP*",
            ...     start="2025-01-01 00:00:00",
            ...     end="2025-01-01 01:00:00"
            ... )
            >>> # Returns: [{"timestamp": "...", "tag": "TEMP_101", "value": 25.5}, ...]
            >>>
            >>> # Hybrid mode with DataFrame output
            >>> df = client.search(
            ...     tag="TEMP*",
            ...     start="2025-01-01 00:00:00",
            ...     output=OutputFormat.DATAFRAME
            ... )
            >>> # Returns: DataFrame with time index and TEMP_* columns
        """
        import urllib.parse

        if not self.datasource:
            raise ValueError(
                "Datasource is required for search. "
                "Please set datasource when creating AspenClient: "
                "AspenClient(base_url=..., datasource='your_datasource')"
            )

        # Determine if we need descriptions for search results
        need_descriptions = include in (IncludeFields.DESCRIPTION, IncludeFields.ALL)

        logger.info(
            f"Searching tags: pattern={tag}, description={description}, "
            f"hybrid_mode={start is not None}"
        )

        # Try cache for search-only mode (hybrid mode caching is handled by read())
        if self._cache and start is None:
            cache_key_params = {
                "tag": tag,
                "description": description,
                "need_descriptions": need_descriptions,
                "case_sensitive": case_sensitive,
                "limit": limit,
                **self._client_cache_identity(),
            }
            cached_result = self._cache.get("search", **cache_key_params)
            if cached_result is not None:
                logger.debug("Cache hit for search")
                return cached_result

        # Step 1: Search for tags
        # If description is provided, use SQL endpoint for efficient server-side search
        if description:
            search_results = self._search_by_sql(
                description=description,
                tag_pattern=tag,
                max_results=limit,
                return_desc=need_descriptions,
            )
        else:
            # Use Browse endpoint for tag name search
            from typing import Any

            results: list[Any] = []

            # Build query parameters
            params = {
                "dataSource": self.datasource,
                "tag": tag,
                "max": limit,
                "getTrendable": 0,
            }

            # Construct Browse endpoint URL with manually encoded query string
            encoded_params = urllib.parse.urlencode(params, safe="*", quote_via=urllib.parse.quote)
            browse_url = f"{self.base_url}/Browse?{encoded_params}"

            logger.info(f"Browse request: GET {browse_url}")
            logger.debug(f"Query params: {params}")

            try:
                response = send(self._client, "GET", browse_url, retries=self.retries)
                logger.debug(f"Response status: {response.status_code}")

                try:
                    data = response.json()
                except ValueError as e:
                    message = f"Browse response is not JSON: {response.text[:200]!r}"
                    raise AspenBrowseError(message) from e

                # Check for API error response
                if "data" in data and isinstance(data["data"], dict):
                    data_obj = data["data"]

                    # Check for error in result
                    if "result" in data_obj:
                        result = data_obj["result"]
                        if isinstance(result, dict) and result.get("er", 0) != 0:
                            error_msg = result.get("es", "Unknown error")
                            raise AspenBrowseError(f"Browse API error: {error_msg}")

                    # Check if tags key exists
                    if "tags" not in data_obj:
                        logger.warning("No 'tags' key in response - search returned no results")
                        tags_data = []
                    else:
                        tags_data = data_obj["tags"]
                        if not isinstance(tags_data, list):
                            raise AspenBrowseError(
                                f"Unexpected Browse response: 'tags' is {type(tags_data).__name__}"
                            )
                else:
                    # Not an empty result: reporting "no tags" would hide a broken response
                    raise AspenBrowseError(f"Unexpected Browse response: {str(data)[:200]}")

                for tag_entry in tags_data:
                    tag_name = tag_entry.get("t", "")
                    tag_desc = tag_entry.get("n", tag_entry.get("m", ""))

                    # Apply case-insensitive filtering if needed
                    if (
                        not case_sensitive
                        and tag
                        and "*" not in tag
                        and "?" not in tag
                        and tag.lower() not in tag_name.lower()
                    ):
                        continue

                    if need_descriptions:
                        results.append({"name": tag_name, "description": tag_desc})
                    else:
                        results.append(tag_name)

                logger.info(f"Found {len(results)} matching tags")
                search_results = results[:limit]

            except Exception as e:
                logger.debug(f"Browse search failed: {type(e).__name__}: {e}")
                raise

        # Step 2: If no start time, return search results (search-only mode)
        if start is None:
            # Cache search results (metadata doesn't change often)
            if self._cache:
                cache_key_params = {
                    "tag": tag,
                    "description": description,
                    "need_descriptions": need_descriptions,
                    "case_sensitive": case_sensitive,
                    "limit": limit,
                    **self._client_cache_identity(),
                }
                self._cache.set("search", search_results, **cache_key_params)
                logger.debug("Cached search results")

            return search_results

        # Step 3: Hybrid mode - extract tag names and read data
        if not search_results:
            logger.info("No tags found, returning empty result")
            # Return appropriate empty structure based on output format
            if output == OutputFormat.DATAFRAME:
                return pd.DataFrame()
            return []

        # Extract tag names from search results
        if isinstance(search_results[0], dict):
            tag_names = [t["name"] for t in search_results]  # type: ignore[index]
        else:
            tag_names = search_results  # type: ignore[assignment]

        logger.info(f"Reading data for {len(tag_names)} tags")

        # Call read() method with the found tags
        return self.read(
            tags=tag_names,
            start=start,
            end=end,
            interval=interval,
            read_type=read_type,
            include=include,
            limit=limit,
            output=output,
        )
