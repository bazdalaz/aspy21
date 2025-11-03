"""XML query generation for Aspen InfoPlus.21 REST API."""

from __future__ import annotations

import pandas as pd

from .models import ReaderType


def build_read_query(
    tag: str,
    start: str,
    end: str,
    read_type: ReaderType,
    interval: int | None = None,
    datasource: str = "",
    max_rows: int = 100000,
    with_description: bool = False,
) -> str:
    """Generate XML query for Aspen REST API data read.

    Args:
        tag: Tag name
        start: Start timestamp (ISO format)
        end: End timestamp (ISO format)
        read_type: Type of read (RAW, INT, etc.)
        interval: Interval in seconds (for aggregated reads)
        datasource: Data source name (default: IP21)
        max_rows: Maximum number of rows to return
        with_description: Include ip_description field in response

    Returns:
        XML query string
    """
    # Convert ISO timestamps to milliseconds since epoch
    start_dt = pd.to_datetime(start)
    end_dt = pd.to_datetime(end)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    # Map ReaderType to Aspen RT codes
    rt_map = {
        ReaderType.RAW: 0,
        ReaderType.INT: 1,
        ReaderType.SNAPSHOT: 2,  # Will use Attribute endpoint
        ReaderType.AVG: 10,
    }
    rt_code = rt_map.get(read_type, 0)

    # Build XML query
    xml = '<Q f="d" allQuotes="1">'
    xml += "<Tag>"
    xml += f"<N><![CDATA[{tag}]]></N>"
    # Only include datasource if specified
    if datasource:
        xml += f"<D><![CDATA[{datasource}]]></D>"
    xml += "<F><![CDATA[VAL]]></F>"

    # Add description field if requested
    if with_description:
        xml += "<F><![CDATA[IP_DESCRIPTION]]></F>"

    xml += "<HF>0</HF>"  # History format: 0=Raw
    xml += f"<St>{start_ms}</St>"
    xml += f"<Et>{end_ms}</Et>"
    xml += f"<RT>{rt_code}</RT>"
    xml += f"<X>{max_rows}</X>"

    # Add interval for aggregated reads
    if interval and rt_code >= 10:
        xml += f"<P>{interval}</P>"
        xml += "<PU>3</PU>"  # Period unit: 3=seconds

    xml += "</Tag>"
    xml += "</Q>"

    return xml


def build_history_sql_query(
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
        read_type: Type of read (RAW or INT)
        interval: Sampling interval in seconds (converted to period in tenths of seconds)
        max_rows: Maximum number of rows to return
        with_description: Include ip_description field in response
        include_status: Include status field in response

    Returns:
        XML query string for SQL endpoint
    """
    from .models import ReaderType

    # Convert timestamps to Aspen SQL format (DD-MMM-YY HH:MM:SS)
    start_dt = pd.to_datetime(start)
    end_dt = pd.to_datetime(end)
    start_sql = start_dt.strftime("%d-%b-%y %H:%M:%S")
    end_sql = end_dt.strftime("%d-%b-%y %H:%M:%S")

    # Map ReaderType to Aspen request parameter
    request_map = {
        ReaderType.RAW: 4,  # Raw historical data
        ReaderType.INT: 1,  # Interpolated data
    }
    request_value = request_map.get(read_type, 4)  # Default to RAW

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

    # Build SQL query - use history(80) for Aspen SQL
    sql_query = f"Select {select_clause} from history(80) where {where_clause}"

    # Build XML request for SQL endpoint with response="Record" for clean JSON arrays
    xml = (
        f'<SQL g="aspy21_history" t="SQLplus" ds="{datasource}" '
        f'dso="CHARINT=N;CHARFLOAT=N;CHARTIME=N;CONVERTERRORS=N" '
        f'm="{max_rows}" to="30" response="Record" s="1">'
        f"<![CDATA[{sql_query}]]>"
        f"</SQL>"
    )

    return xml


def build_snapshot_sql_query(
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


def build_sql_search_query(
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
