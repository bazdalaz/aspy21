"""Main client for interacting with Aspen InfoPlus.21 REST API."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from typing import TYPE_CHECKING

import httpx
import pandas as pd

from .models import ReaderType
from .query_builder import build_sql_search_query

if TYPE_CHECKING:
    from httpx import Auth

logger = logging.getLogger(__name__)


def configure_logging(level: str | None = None) -> None:
    """Configure logging level for aspy21 library.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
               If None, reads from ASPEN_LOG_LEVEL environment variable.
               Defaults to WARNING if not set.
    """
    if level is None:
        level = os.getenv("ASPEN_LOG_LEVEL", "WARNING")

    numeric_level = getattr(logging, level.upper(), logging.WARNING)
    logger.setLevel(numeric_level)

    # Only add handler if logger doesn't have one already
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)


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
        timeout: float = 30.0,
        verify_ssl: bool = True,
        datasource: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the Aspen client.

        Args:
            base_url: Base URL of the Aspen ProcessData REST API
            auth: Authentication as (username, password) tuple or httpx Auth object.
                  If None, no authentication is used.
            timeout: Request timeout in seconds (default: 30.0)
            verify_ssl: Whether to verify SSL certificates (default: True)
            datasource: Aspen datasource name. If None, uses server default.
            http_client: Optional httpx.Client instance. If None, creates a new client.
                        Useful for dependency injection and testing.

        Example:
            Using context manager with authentication:
                >>> with AspenClient(
                ...     base_url="https://aspen.example.com/ProcessData",
                ...     auth=("user", "pass")
                ... ) as client:
                ...     df = client.read(["TAG1"], "2025-01-01", "2025-01-02")

            Without authentication:
                >>> with AspenClient(base_url="http://aspen.example.com/ProcessData") as client:
                ...     df = client.read(["TAG1"], "2025-01-01", "2025-01-02")

            With datasource for search:
                >>> with AspenClient(
                ...     base_url="https://aspen.example.com/ProcessData",
                ...     auth=("user", "pass"),
                ...     datasource="IP21"
                ... ) as client:
                ...     tags = client.search(tag="TEMP*")

            With custom HTTP client (for testing or custom configuration):
                >>> client = httpx.Client(timeout=60.0, verify=False)
                >>> aspen = AspenClient(
                ...     base_url="https://aspen.example.com/ProcessData",
                ...     http_client=client
                ... )
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.datasource = datasource or ""  # Empty string = use server default
        self.auth = auth

        # Support dependency injection of HTTP client
        self._owns_client = http_client is None
        if http_client is None:
            self._client = httpx.Client(timeout=timeout, verify=verify_ssl, auth=auth)
        else:
            self._client = http_client

        # Initialize reader strategies
        from .readers import SnapshotReader, SqlHistoryReader, XmlHistoryReader

        self._readers = [
            SnapshotReader(self.base_url, self.datasource, self._client),
            SqlHistoryReader(self.base_url, self.datasource, self._client),
            XmlHistoryReader(self.base_url, self.datasource, self._client),
        ]

        logger.info(f"Initialized AspenClient for {self.base_url}")
        logger.debug(
            f"Config: timeout={timeout}s, verify_ssl={verify_ssl}, datasource={datasource}"
        )

    def __enter__(self) -> AspenClient:
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

    def read(
        self,
        tags: Iterable[str],
        start: str | None = None,
        end: str | None = None,
        interval: int | None = None,
        read_type: ReaderType = ReaderType.INT,
        include_status: bool = False,
        max_rows: int = 100000,
        as_df: bool = False,
        with_description: bool = False,
    ) -> pd.DataFrame | list[dict]:
        """Read process data for multiple tags.

        Args:
            tags: List of tag names to retrieve
            start: Start timestamp (ISO format or compatible string). If omitted, defaults to
                SNAPSHOT read.
            end: End timestamp (ISO format or compatible string). If omitted, defaults to
                SNAPSHOT read.
            interval: Optional interval in seconds for aggregated data (AVG reads)
            read_type: Type of data retrieval (RAW, INT, SNAPSHOT, AVG) (default: INT)
            include_status: Include status column in output (default: False)
            max_rows: Maximum number of rows to return per tag (default: 100000)
            as_df: Return data as pandas DataFrame instead of JSON list (default: False)
            with_description: Include tag descriptions in response (default: False).
                             Note: Some Aspen servers may not support this field.

        Returns:
            If as_df=True: pandas DataFrame with time index and columns for each tag.
                           If include_status=True, includes a 'status' column.
            If as_df=False: List of dictionaries, each containing:
                            - timestamp: ISO format timestamp string
                            - tag: Tag name
                            - description: Tag description (when requested via with_description)
                            - value: Tag value

        Example:
            >>> # JSON output (default)
            >>> client = AspenClient("https://aspen.example.com/ProcessData")
            >>> data = client.read(
            ...     ["ATI111"],
            ...     start="2025-01-01 00:00:00",
            ...     end="2025-01-01 01:00:00"
            ... )
            >>> # Returns: [
            >>> #   {"timestamp": "2025-01-01T00:00:00", "tag": "ATI111",
            >>> #    "description": "Temperature sensor", "value": 25.5},
            >>> #   ...
            >>> # ]

            >>> # DataFrame output
            >>> df = client.read(
            ...     ["ATI111", "AP101.PV"],
            ...     start="2025-01-01 00:00:00",
            ...     end="2025-01-01 01:00:00",
            ...     as_df=True
            ... )
        """
        from .readers import DataFormatter

        tags_list = list(tags)
        if not tags_list:
            raise ValueError("At least one tag is required")

        # Auto-detect SNAPSHOT reads when start/end not provided
        effective_read_type = read_type
        if start is None or end is None:
            if effective_read_type != ReaderType.SNAPSHOT:
                logger.info(
                    "No start/end provided; defaulting to SNAPSHOT read for %d tag(s)",
                    len(tags_list),
                )
            effective_read_type = ReaderType.SNAPSHOT

        logger.debug(f"Tags: {tags_list}")
        logger.debug(f"Reader type: {effective_read_type.value}, Interval: {interval}")

        # Select appropriate reader strategy
        for reader in self._readers:
            if reader.can_handle(effective_read_type, start, end):
                frames, tag_descriptions = reader.read(
                    tags=tags_list,
                    start=start,
                    end=end,
                    interval=interval,
                    read_type=effective_read_type,
                    include_status=include_status,
                    max_rows=max_rows,
                    with_description=with_description,
                )
                break
        else:
            raise ValueError(f"No reader available for read_type={effective_read_type}")

        # Format output using formatter
        return DataFormatter.format_output(
            frames=frames,
            tags=tags_list,
            tag_descriptions=tag_descriptions,
            as_df=as_df,
            include_status=include_status,
            with_description=with_description,
        )

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
            raise ValueError(
                "Datasource is required for SQL search. "
                "Please set datasource when creating AspenClient: "
                "AspenClient(base_url=..., datasource='your_datasource')"
            )

        # Build XML query for SQL endpoint
        xml = build_sql_search_query(
            datasource=self.datasource,
            description=description,
            tag_pattern=tag_pattern,
            max_results=max_results,
        )

        logger.debug(f"SQL query XML: {xml}")

        sql_url = f"{self.base_url}/SQL"
        logger.info(f"SQL request: POST {sql_url}")

        try:
            response = self._client.post(sql_url, content=xml, headers={"Content-Type": "text/xml"})

            logger.debug(f"Response status: {response.status_code}")
            response.raise_for_status()

            data = response.json()
            logger.debug(f"SQL response keys: {list(data.keys())}")

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

            # Check for errors
            if "result" in result_set:
                result = result_set["result"]
                if isinstance(result, dict) and result.get("er", 0) != 0:
                    error_msg = result.get("es", "Unknown error")
                    logger.error(f"API error from SQL endpoint: {error_msg}")
                    raise ValueError(f"SQL API error: {error_msg}")

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
            logger.error(f"Error in SQL search: {type(e).__name__}: {e}")
            raise

    def search(
        self,
        tag: str = "*",
        description: str | None = None,
        case_sensitive: bool = False,
        max_results: int = 10000,
        return_desc: bool = True,
    ) -> list[dict[str, str]] | list[str]:
        """Search for tags by name pattern and/or description.

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
            max_results: Maximum number of results to return (default: 10000)
            return_desc: Whether to return descriptions (default: True).
                        If True, returns list of dicts with 'name' and 'description'.
                        If False, returns list of tag name strings only.

        Returns:
            If return_desc=True: List of dictionaries with 'name' and 'description' keys.
            If return_desc=False: List of tag name strings.

        Raises:
            ValueError: If datasource is not configured

        Example:
            >>> # Find all temperature tags with descriptions
            >>> tags = client.search(tag="TEMP*")
            >>> # Returns: [{"name": "TEMP_101", "description": "Reactor temp"}, ...]
            >>>
            >>> # Get just tag names without descriptions
            >>> tag_names = client.search(tag="TEMP*", return_desc=False)
            >>> # Returns: ["TEMP_101", "TEMP_102", ...]
            >>>
            >>> # Search by description only
            >>> tags = client.search(description="reactor")
            >>>
            >>> # Combine name and description
            >>> tags = client.search(tag="AI_1*", description="pressure")
            >>>
            >>> # Process results with descriptions
            >>> for tag in tags:
            ...     print(f"{tag['name']}: {tag['description']}")
        """
        import urllib.parse

        if not self.datasource:
            raise ValueError(
                "Datasource is required for search. "
                "Please set datasource when creating AspenClient: "
                "AspenClient(base_url=..., datasource='your_datasource')"
            )

        logger.info(f"Searching tags: pattern={tag}, description={description}")

        # If description is provided, use SQL endpoint for efficient server-side search
        if description:
            return self._search_by_sql(
                description=description,
                tag_pattern=tag,
                max_results=max_results,
                return_desc=return_desc,
            )

        # Otherwise, use Browse endpoint for tag name search
        # Use Any type for results list to handle both dict and str
        from typing import Any

        results: list[Any] = []

        # Build query parameters
        # Note: The key is "dataSource" (camelCase)
        params = {
            "dataSource": self.datasource,
            "tag": tag,
            "max": max_results,
            "getTrendable": 0,
        }

        # Construct Browse endpoint URL with manually encoded query string
        # We need to keep * unencoded for wildcard matching
        # Following tagreader's approach: encode with safe="*"
        encoded_params = urllib.parse.urlencode(params, safe="*", quote_via=urllib.parse.quote)
        browse_url = f"{self.base_url}/Browse?{encoded_params}"

        logger.info(f"Browse request: GET {browse_url}")
        logger.debug(f"Query params: {params}")

        try:
            # Make GET request to Browse endpoint
            # URL already contains query string, so don't pass params again
            response = self._client.get(browse_url)

            # Log the actual request details
            logger.debug(f"Request URL: {response.request.url}")
            logger.debug(f"Request method: {response.request.method}")
            logger.debug(f"Response status: {response.status_code}")

            response.raise_for_status()
            data = response.json()

            logger.debug(f"Browse response keys: {list(data.keys())}")

            # Check for API error response
            if "data" in data and isinstance(data["data"], dict):
                data_obj = data["data"]
                logger.debug(f"data['data'] keys: {list(data_obj.keys())}")

                # Check for error in result
                if "result" in data_obj:
                    result = data_obj["result"]
                    if isinstance(result, dict) and result.get("er", 0) != 0:
                        error_msg = result.get("es", "Unknown error")
                        logger.error(f"API error from Browse endpoint: {error_msg}")
                        raise ValueError(f"Browse API error: {error_msg}")

                # Check if tags key exists
                if "tags" not in data_obj:
                    logger.warning("No 'tags' key in response - search returned no results")
                    logger.debug(f"Full response: {data}")
                    return []

                tags_data = data_obj["tags"]
            else:
                logger.error(f"Unexpected response structure: {data}")
                return []

            logger.debug(f"tags_data type: {type(tags_data)}, length: {len(tags_data)}")

            if not tags_data:
                logger.info("Search returned 0 tags")
                return []

            for tag_entry in tags_data:
                tag_name = tag_entry.get("t", "")
                # Response contains "m" (map type) like "IP_ANALOGMAP", "KPI_VALUEMAP"
                # and optionally "n" (description). Use "n" if available, otherwise "m"
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

                if return_desc:
                    results.append({"name": tag_name, "description": tag_desc})
                else:
                    results.append(tag_name)

            logger.info(f"Found {len(results)} matching tags")
            return results[:max_results]

        except Exception as e:
            logger.error(f"Error searching tags: {type(e).__name__}: {e}")
            raise
