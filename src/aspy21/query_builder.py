"""SQL query generation for Aspen InfoPlus.21 REST API.

This module implements the Strategy Pattern for generating different query types.
Each builder handles a specific query format (SQL history, snapshot, search, aggregates).
"""

from __future__ import annotations

import logging
from abc import ABC

import pandas as pd

from .models import ReaderType

logger = logging.getLogger(__name__)


class QueryBuilder(ABC):  # noqa: B024
    """Abstract base class for query building strategies.

    Each builder implements a specific strategy for generating queries
    for different Aspen API endpoints and query types.

    Note: Subclasses implement build() with signatures specific to their
    query type. The varying signatures are intentional as each builder
    handles fundamentally different query requirements.
    """

    pass


class SqlHistoryQueryBuilder(QueryBuilder):
    """Query builder for SQL history endpoint (batched multi-tag queries)."""

    def build(
        self,
        tags: list[str] | str,
        start: str,
        end: str,
        datasource: str,
        read_type: ReaderType,
        interval: int | None = None,
        max_rows: int = 100000,
        with_description: bool = False,
        include_status: bool = False,
    ) -> str:
        """Generate SQL query for historical data read.

        Args:
            tags: Tag name(s) - single tag string or list of tags for batched query
            start: Start timestamp (ISO format)
            end: End timestamp (ISO format)
            datasource: Aspen datasource name
            read_type: Type of read (RAW, INT, or AVG)
            interval: Sampling interval in seconds (converted to period in tenths of seconds)
            max_rows: Maximum number of rows to return
            with_description: Include ip_description field in response
            include_status: Include status field in response

        Returns:
            XML query string for SQL endpoint
        """
        # Convert timestamps to Aspen SQL format (DD-MMM-YY HH:MM:SS)
        start_dt = pd.to_datetime(start)
        end_dt = pd.to_datetime(end)
        start_sql = start_dt.strftime("%d-%b-%y %H:%M:%S")
        end_sql = end_dt.strftime("%d-%b-%y %H:%M:%S")

        # Map ReaderType to Aspen request parameter
        request_map = {
            ReaderType.RAW: 4,  # Raw historical data
            ReaderType.INT: 5,  # Interpolated data with data point to current value
        }
        request_value = request_map.get(read_type, ReaderType.INT)  # Default to INTERPOLATED

        # Build SELECT clause with optional fields
        select_fields = ["ts", "name"]

        if with_description:
            select_fields.append("name->ip_description")

        select_fields.append("value")

        if include_status:
            select_fields.append("status")

        select_clause = ", ".join(select_fields)

        # Convert tags to list if single string provided
        tags_list = [tags] if isinstance(tags, str) else tags

        # Build WHERE clause with request parameter
        # Use IN clause for multiple tags, single equality for one tag
        if len(tags_list) == 1:
            name_clause = f"name='{tags_list[0]}'"
        else:
            # Build IN clause with quoted tag names
            tag_list_str = ", ".join(f"'{tag}'" for tag in tags_list)
            name_clause = f"name in ({tag_list_str})"

        where_clauses = [
            name_clause,
            f"ts between '{start_sql}' and '{end_sql}'",
            f"request={request_value}",
        ]

        # Add period if interval is specified (convert seconds to tenths of seconds)
        if interval is not None:
            period = interval * 10  # Convert seconds to tenths of seconds
            where_clauses.append(f"period={period}")

        where_clause = " and ".join(where_clauses)

        # Build SQL query - use history(80) for field length
        sql_query = f"Select {select_clause} from history(80) where {where_clause}"

        # Build XML request for SQL endpoint with response="Record" for clean JSON arrays
        xml = (
            f'<SQL g="aspy21_history" t="SQLplus" ds="{datasource}" '
            f'dso="CHARINT=N;CHARFLOAT=N;CHARTIME=N;CONVERTERRORS=N" '
            f'm="{max_rows}" to="30   " response="Record" s="1">'  # s=1 for Select
            f"<![CDATA[{sql_query}]]>"
            f"</SQL>"
        )

        return xml


class SqlSnapshotQueryBuilder(QueryBuilder):
    """Query builder for SQL snapshot endpoint (current values)."""

    def build(
        self,
        tags: list[str] | str,
        datasource: str,
        with_description: bool = False,
    ) -> str:
        """Generate SQL query for current snapshot values.

        Args:
            tags: One or more tag names to fetch.
            datasource: Aspen datasource name.
            with_description: Include ip_description field in response.

        Returns:
            XML query string for SQL snapshot endpoint.
        """
        tag_list = [tags] if isinstance(tags, str) else tags
        if not tag_list:
            raise ValueError("At least one tag is required for snapshot query")

        select_fields = ["name"]
        if with_description:
            select_fields.append("name->ip_description")
        select_fields.append("name->ip_input_value")
        select_fields.append("name->ip_input_quality")

        select_clause = ", ".join(select_fields)
        tag_list_str = ", ".join(f"'{tag}'" for tag in tag_list)

        sql_query = f"Select {select_clause} from all_records where name in ({tag_list_str})"

        xml = (
            f'<SQL g="aspy21_snapshot" t="SQLplus" ds="{datasource}" '
            f'dso="CHARINT=N;CHARFLOAT=N;CHARTIME=N;CONVERTERRORS=N" '
            f'm="{len(tag_list)}" to="30" response="Record" s="1">'
            f"<![CDATA[{sql_query}]]>"
            f"</SQL>"
        )

        return xml


class SqlSearchQueryBuilder(QueryBuilder):
    """Query builder for SQL search endpoint (tag search by description/name)."""

    def build(
        self,
        datasource: str,
        description: str,
        tag_pattern: str = "*",
        max_results: int = 10000,
    ) -> str:
        """Generate XML query for SQL-based tag search.

        Args:
            datasource: Aspen datasource name
            description: Description pattern to search for (supports * wildcards)
            tag_pattern: Tag name pattern (supports * and ? wildcards)
            max_results: Maximum number of results

        Returns:
            XML query string for SQL endpoint
        """
        # Build SQL query - search for description pattern
        # Note: SQL LIKE uses % as wildcard, not *
        sql_pattern = description.replace("*", "%")
        if not sql_pattern.startswith("%"):
            sql_pattern = f"%{sql_pattern}%"

        # Build WHERE clause - filter by both name and description in SQL
        where_clauses = [f"d like '{sql_pattern}'"]

        # Add name pattern filter if not wildcard
        if tag_pattern != "*":
            name_pattern = tag_pattern.replace("*", "%").replace("?", "_")
            # Add wildcards to name pattern if not already present
            if "%" not in name_pattern and "_" not in name_pattern:
                name_pattern = f"%{name_pattern}%"
            where_clauses.append(f"name like '{name_pattern}'")

        where_clause = " and ".join(where_clauses)

        sql_query = (
            f"Select name, name->ip_description d, name->ip_input_value "
            f"from all_records where {where_clause}"
        )

        # Build XML request for SQL endpoint
        xml = (
            f'<SQL g="aspy21_search" t="SQLplus" ds="{datasource}" '
            f'dso="CHARINT=N;CHARFLOAT=N;CHARTIME=N;CONVERTERRORS=N" '
            f'm="{max_results}" to="30" response="Original" s="1">'
            f"<![CDATA[{sql_query}]]>"
            f"</SQL>"
        )

        return xml


class SqlAggregatesQueryBuilder(QueryBuilder):
    """Query builder for SQL aggregates table queries."""

    def build(
        self,
        tags: list[str] | str,
        start: str,
        end: str,
        datasource: str,
        read_type: ReaderType,
        interval: int | None = None,
        with_description: bool = False,
        include_status: bool = False,
    ) -> str:
        """Generate SQL query for aggregates table.

        Args:
            tags: Tag name(s) - single tag string or list of tags
            start: Start timestamp (ISO format)
            end: End timestamp (ISO format)
            datasource: Aspen datasource name
            read_type: Type of aggregation (MIN, MAX, AVG, RNG)
            with_description: Include ip_description field in response
            include_status: Include status field in response (not supported for aggregates)

        Returns:
            XML query string for SQL endpoint
        """
        import xml.etree.ElementTree as ET

        # Convert tags to list if string
        tags_list = [tags] if isinstance(tags, str) else tags

        # Calculate period in tenths of seconds
        # - If interval provided: period = interval * 10 (returns multiple values)
        # - If no interval: period = (end - start) * 10 (returns single value)
        if interval:
            period_tenths = interval * 10
            logger.debug(f"Using interval={interval}s, period={period_tenths} tenths of seconds")
        else:
            start_dt = pd.to_datetime(start)
            end_dt = pd.to_datetime(end)
            period_seconds = int((end_dt - start_dt).total_seconds())
            period_tenths = period_seconds * 10
            logger.debug(f"Period from time range: {period_seconds}s = {period_tenths} tenths")

        # Map ReaderType to SQL column name
        agg_column_map = {
            ReaderType.MIN: "min",
            ReaderType.MAX: "max",
            ReaderType.AVG: "avg",
            ReaderType.RNG: "rng",
        }

        column_name = agg_column_map.get(read_type)
        if column_name is None:
            raise ValueError(f"Unsupported read_type for aggregates: {read_type}")

        # Build SELECT clause
        select_fields = ["ts", "name", column_name]
        if with_description:
            select_fields.append("name->ip_description")

        select_clause = ", ".join(select_fields)

        # Build SQL query for multiple tags using UNION ALL
        sql_queries = []
        for tag in tags_list:
            sql = (
                f"SELECT {select_clause} FROM aggregates "
                f"WHERE name = '{tag}' "
                f"AND ts BETWEEN '{start}' AND '{end}' "
                f"AND period = {period_tenths}"
            )
            sql_queries.append(sql)

        # Combine with UNION ALL for multiple tags
        full_sql = " UNION ALL ".join(sql_queries)
        logger.debug(f"Generated SQL query: {full_sql}")

        # Wrap in XML format
        root = ET.Element("Sql")
        root.text = full_sql

        ET.SubElement(root, "Datasource").text = datasource

        return ET.tostring(root, encoding="unicode")
