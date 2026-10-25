"""Check how a live IP.21 server applies the query timeout (the to="..." attribute).

The client sends its HTTP read timeout as the server's query timeout. This script sends
one slow RAW query (all ASPEN_TEST_TAGS over --days) several times with different to=
values and prints what comes back: how long it took, the HTTP status, the number of rows,
and the error IP.21 reports, if any. It shows whether the server stops a query when to=
runs out, what it returns then, and what to="0" means.

The HTTP client waits up to 10 minutes, so only the server's timeout can stop a query.

Reads connection settings from .env in the project root (see .env.example).

Usage:
    python scripts/check_server_timeout.py [--days 30]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv

from aspy21 import AspenSqlError, ReaderType
from aspy21.errors import raise_for_sql_error
from aspy21.query_builder import SqlHistoryQueryBuilder

load_dotenv(Path(__file__).parent.parent / ".env")


def describe(body: object) -> str:
    """Summarize a SQL response: row count, or the error IP.21 reported."""
    try:
        raise_for_sql_error(body)
    except AspenSqlError as e:
        return f"AspenSqlError: {e}"
    if isinstance(body, list):
        return f"{len(body)} rows"
    return f"{type(body).__name__}: {str(body)[:300]}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the server-side query timeout")
    parser.add_argument("--days", type=float, default=30.0, help="time range (default 30)")
    args = parser.parse_args()

    base_url = os.getenv("ASPEN_BASE_URL")
    datasource = os.getenv("ASPEN_DATASOURCE")
    tags = [t.strip() for t in os.getenv("ASPEN_TEST_TAGS", "").split(",") if t.strip()]
    if not base_url or not datasource or not tags:
        print("ERROR: set ASPEN_BASE_URL, ASPEN_DATASOURCE and ASPEN_TEST_TAGS in .env")
        sys.exit(1)

    username, password = os.getenv("ASPEN_USERNAME"), os.getenv("ASPEN_PASSWORD")
    end = datetime.now().replace(microsecond=0)
    start = end - timedelta(days=args.days)

    print(f"Server: {base_url} ({datasource})")
    print(f"Query: RAW, {len(tags)} tag(s), {start} to {end}")

    with httpx.Client(
        timeout=600,
        verify=os.getenv("ASPEN_VERIFY_SSL", "False").lower() == "true",
        auth=(username, password) if username and password else None,
    ) as http:
        for to in (30, 1, 0):
            xml = SqlHistoryQueryBuilder().build(
                tags,
                str(start),
                str(end),
                datasource,
                ReaderType.RAW,
                max_rows=10_000_000,
                timeout=to,
            )
            began = time.monotonic()
            try:
                response = http.post(
                    f"{base_url.rstrip('/')}/SQL",
                    content=xml,
                    headers={"Content-Type": "text/xml"},
                )
            except httpx.HTTPError as e:
                print(f'  to="{to}": {time.monotonic() - began:.1f}s, {type(e).__name__}: {e}')
                continue
            elapsed = time.monotonic() - began
            try:
                summary = describe(response.json())
            except ValueError:
                summary = f"not JSON ({len(response.text)} chars): {response.text[:300]!r}"
            print(f'  to="{to}": {elapsed:.1f}s, HTTP {response.status_code}, {summary}')

    print('\nIf to="30" took under ~2 seconds, rerun with a larger --days.')


if __name__ == "__main__":
    main()
