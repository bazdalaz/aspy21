"""Check how a live IP.21 server applies row limits and intervals to RAW reads.

read(tags, limit=N) promises up to N rows per tag. IP.21 applies a query's row limit to
the whole result and returns it grouped by tag, so the client re-reads tags that a
multi-tag query cut short. This script checks that every tag gets its N rows, and whether
the server ignores the period the client sends when a RAW read has an interval.

Reads connection settings from .env in the project root (see .env.example) and uses the
tags in ASPEN_TEST_TAGS that have more than --limit values in the time range.

Usage:
    python scripts/check_row_limits.py [--hours 1] [--limit 10]
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from aspy21 import AspenClient, OutputFormat, ReaderType, configure_logging

load_dotenv(Path(__file__).parent.parent / ".env")
configure_logging(os.getenv("ASPEN_LOG_LEVEL", "ERROR"))

failures: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def counts(
    client: AspenClient,
    tags: list[str],
    span: tuple[str, str],
    limit: int = 100_000,
    interval: int | None = None,
) -> dict[str, int]:
    """Read RAW data and return the number of values per tag."""
    df = client.read(
        tags,
        start=span[0],
        end=span[1],
        interval=interval,
        read_type=ReaderType.RAW,
        limit=limit,
        output=OutputFormat.DATAFRAME,
    )
    return {tag: int(df[tag].count()) if tag in df.columns else 0 for tag in tags}


def main() -> None:
    parser = argparse.ArgumentParser(description="Check row limits and intervals of RAW reads")
    parser.add_argument("--hours", type=float, default=1.0, help="time range (default 1)")
    parser.add_argument("--limit", type=int, default=10, help="rows per tag (default 10)")
    args = parser.parse_args()

    base_url = os.getenv("ASPEN_BASE_URL")
    datasource = os.getenv("ASPEN_DATASOURCE")
    tags = [t.strip() for t in os.getenv("ASPEN_TEST_TAGS", "").split(",") if t.strip()]
    if not base_url or not datasource or not tags:
        print("ERROR: set ASPEN_BASE_URL, ASPEN_DATASOURCE and ASPEN_TEST_TAGS in .env")
        sys.exit(1)

    username, password = os.getenv("ASPEN_USERNAME"), os.getenv("ASPEN_PASSWORD")
    end = datetime.now().replace(microsecond=0)
    start = end - timedelta(hours=args.hours)
    span = (str(start), str(end))
    limit = args.limit

    print(f"Server: {base_url} ({datasource})")
    print(f"Range: {start} to {end}, limit={limit}")

    with AspenClient(
        base_url,
        datasource=datasource,
        auth=(username, password) if username and password else None,
        server_timezone=os.getenv("ASPEN_SERVER_TIMEZONE") or None,
        verify_ssl=os.getenv("ASPEN_VERIFY_SSL", "False").lower() == "true",
    ) as client:
        print("\n=== 1. Values per tag, one tag per read, no limit (reference)")
        reference = {tag: counts(client, [tag], span)[tag] for tag in tags}
        for tag, n in reference.items():
            print(f"  [INFO] {tag}: {n} values")

        dense = [tag for tag in tags if reference[tag] > limit]
        if len(dense) < 2:
            print(
                f"\nNeed 2 tags with more than {limit} values; found {len(dense)}. "
                "Use a longer --hours, a smaller --limit, or more ASPEN_TEST_TAGS."
            )
            sys.exit(1)

        print(f"\n=== 2. limit={limit} per tag, several tags in one read")
        for order in (dense, dense[::-1]):
            got = counts(client, order, span, limit=limit)
            print(f"  [INFO] order {order}: {got}")
            short = [tag for tag in order if got[tag] < limit]
            check(f"every tag gets {limit} rows ({order[0]} first)", not short, short or "")

        print(f"\n=== 3. Same read with limit={limit}, one tag at a time")
        for tag in dense[:2]:
            got = counts(client, [tag], span, limit=limit)[tag]
            check(f"{tag} gets {limit} rows", got == limit, f"{got} rows")

        print("\n=== 4. RAW read with and without interval=600")
        tag = dense[0]
        without = counts(client, [tag], span)[tag]
        with_interval = counts(client, [tag], span, interval=600)[tag]
        print(f"  [INFO] {tag}: {without} rows without interval, {with_interval} with")
        check("interval does not change RAW results", without == with_interval)

    print(f"\n{'All checks passed' if not failures else f'{len(failures)} check(s) failed'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
