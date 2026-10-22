"""Base reader interface for Aspen data reading strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import pandas as pd

from ..retry import send

if TYPE_CHECKING:
    from datetime import tzinfo

    import httpx

    from ..models import ReaderType


class BaseReader(ABC):
    """Abstract base class for Aspen data readers.

    Each reader implements a specific strategy for reading data from
    the Aspen InfoPlus.21 REST API (e.g., snapshot, SQL history, XML history).
    """

    def __init__(
        self,
        base_url: str,
        datasource: str,
        http_client: httpx.Client,
        server_timezone: str | tzinfo | None = None,
        *,
        retries: int = 0,
    ) -> None:
        """Initialize the reader.

        Args:
            base_url: Base URL of the Aspen ProcessData REST API
            datasource: Aspen datasource name
            http_client: HTTP client instance for making requests
            server_timezone: Time zone of the IP.21 server, or None for this machine's zone
            retries: How many times to repeat a request that failed transiently
        """
        self.base_url = base_url
        self.datasource = datasource
        self.http_client = http_client
        self.server_timezone = server_timezone
        self.retries = retries

    def _post_sql(self, xml_query: str) -> httpx.Response:
        """POST a query to the SQL endpoint, retrying transient failures.

        Args:
            xml_query: XML request body

        Returns:
            Successful response
        """
        return send(
            self.http_client,
            "POST",
            f"{self.base_url}/SQL",
            retries=self.retries,
            content=xml_query,
            headers={"Content-Type": "text/xml"},
        )

    @abstractmethod
    def read(
        self,
        tags: list[str],
        start: str | None,
        end: str | None,
        interval: int | None,
        read_type: ReaderType,
        include_status: bool,
        max_rows: int,
        with_description: bool,
    ) -> tuple[list[pd.DataFrame], dict[str, str]]:
        """Read data for the given tags.

        Args:
            tags: List of tag names to retrieve
            start: Start timestamp
            end: End timestamp
            interval: Interval in seconds for aggregated data
            read_type: Type of data retrieval (RAW, INT, SNAPSHOT, AVG)
            include_status: Include status column in output
            max_rows: Maximum number of rows to return per tag
            with_description: Include tag descriptions in response

        Returns:
            Tuple of (list of DataFrames, dict of tag descriptions)
        """

    @abstractmethod
    def can_handle(
        self,
        read_type: ReaderType,
        start: str | None,
        end: str | None,
    ) -> bool:
        """Check if this reader can handle the given request.

        Args:
            read_type: Type of data retrieval
            start: Start timestamp
            end: End timestamp

        Returns:
            True if this reader can handle the request
        """
