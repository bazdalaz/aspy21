"""Time large RAW reads against a live IP.21 server and check the results agree.

Reads every tag in ASPEN_TEST_TAGS over --days as a DataFrame and as JSON, and reports
how long the server took and how long the client took to parse and format the rows.
Checks that both outputs hold the same number of values per tag and that the time index
is sorted and has no missing timestamps.

Reads connection settings from .env in the project root (see .env.example).

Usage:
    python scripts/check_read_speed.py [--days 30]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

import aspy21
from aspy21 import AspenClient, OutputFormat, ReaderType, configure_logging
from aspy21.readers import base_reader

load_dotenv(Path(__file__).parent.parent / ".env")
configure_logging(os.getenv("ASPEN_LOG_LEVEL", "ERROR"))

failures: list[str] = []
server_seconds = 0.0

_send = base_reader.send


def timed_send(*args, **kwargs):
    """Send a request and add its time (including the downloaded body) to server_seconds."""
    global server_seconds
    started = time.perf_counter()
    response = _send(*args, **kwargs)
    server_seconds += time.perf_counter() - started
    return response


base_reader.send = timed_send


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def timed_read(client: AspenClient, tags: list[str], span: tuple[str, str], output):
    """Read RAW data; return the result, total seconds and server seconds."""
    global server_seconds
    server_seconds = 0.0
    started = time.perf_counter()
    result = client.read(tags, start=span[0], end=span[1], read_type=ReaderType.RAW, output=output)
    return result, time.perf_counter() - started, server_seconds


def main() -> None:
    parser = argparse.ArgumentParser(description="Time large RAW reads")
    parser.add_argument("--days", type=float, default=30.0, help="time range (default 30)")
    args = parser.parse_args()

    base_url = os.getenv("ASPEN_BASE_URL")
    datasource = os.getenv("ASPEN_DATASOURCE")
    tags = [t.strip() for t in os.getenv("ASPEN_TEST_TAGS", "").split(",") if t.strip()]
    if not base_url or not datasource or not tags:
        print("ERROR: set ASPEN_BASE_URL, ASPEN_DATASOURCE and ASPEN_TEST_TAGS in .env")
        sys.exit(1)

    username, password = os.getenv("ASPEN_USERNAME"), os.getenv("ASPEN_PASSWORD")
    end = datetime.now().replace(microsecond=0) - timedelta(hours=1)
    start = end - timedelta(days=args.days)
    span = (str(start), str(end))

    print(f"aspy21 {aspy21.__version__}, {len(tags)} tag(s), {start} to {end}")

    with AspenClient(
        base_url,
        datasource=datasource,
        auth=(username, password) if username and password else None,
        server_timezone=os.getenv("ASPEN_SERVER_TIMEZONE") or None,
        verify_ssl=os.getenv("ASPEN_VERIFY_SSL", "True").lower() == "true",
        timeout=300.0,
    ) as client:
        print("\n=== 1. DataFrame")
        df, total, server = timed_read(client, tags, span, OutputFormat.DATAFRAME)
        df_counts = {tag: int(df[tag].count()) if tag in df.columns else 0 for tag in tags}
        print(f"  [INFO] {len(df)} rows, {sum(df_counts.values())} values")
        print(f"  [INFO] {total:.2f}s total: server {server:.2f}s, client {total - server:.2f}s")
        check("time index is sorted", df.index.is_monotonic_increasing)
        check("no missing timestamps", not df.index.hasnans)

        print("\n=== 2. JSON")
        records, total, server = timed_read(client, tags, span, OutputFormat.JSON)
        json_counts = Counter(record["tag"] for record in records)
        print(f"  [INFO] {len(records)} records")
        print(f"  [INFO] {total:.2f}s total: server {server:.2f}s, client {total - server:.2f}s")
        for tag in tags:
            check(
                f"{tag}: same values as DataFrame",
                json_counts.get(tag, 0) == df_counts[tag],
                f"{json_counts.get(tag, 0)} JSON, {df_counts[tag]} DataFrame",
            )

    print(f"\n{'All checks passed' if not failures else f'{len(failures)} check(s) failed'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
