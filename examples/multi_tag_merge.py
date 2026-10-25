"""Check how reads of several tags are merged into one result.

Each tag's values are aligned on one time index. A tag with no value at a timestamp
gets NaN there (DataFrame) or no record (JSON). Raw history can hold several values of
one tag at the same timestamp; every one of them is kept.

The script runs two parts:

1. Offline: mocked server responses with gaps, duplicate timestamps and integer values
   (needs respx: pip install respx)
2. Live: a RAW read of ASPEN_TEST_TAGS from the server in .env, checking that the
   DataFrame and JSON outputs hold the same values (skipped without ASPEN_BASE_URL)

Usage:
    python examples/multi_tag_merge.py [--hours N]
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv

from aspy21 import AspenClient, OutputFormat, ReaderType, configure_logging

load_dotenv(Path(__file__).parent.parent / ".env")
configure_logging(os.getenv("ASPEN_LOG_LEVEL", "ERROR"))

MOCK_URL = "https://mock/ProcessData/AtProcessDataREST.dll"

failures: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def record(tag: str, minute: int, value: object) -> dict:
    return {"name": tag, "ts": f"2025-01-01T00:{minute:02d}:00Z", "value": value, "status": 0}


def mock_read(body: list[dict], tags: list[str], output: OutputFormat) -> pd.DataFrame | list:
    import respx

    with respx.mock:
        respx.post(f"{MOCK_URL}/SQL").mock(return_value=httpx.Response(200, json=body))
        with AspenClient(MOCK_URL, datasource="IP21", retries=0) as client:
            return client.read(
                tags,
                start="2025-01-01 00:00:00",
                end="2025-01-01 01:00:00",
                read_type=ReaderType.RAW,
                output=output,
            )


def run_offline() -> None:
    try:
        import respx  # noqa: F401
    except ImportError:
        print("\nOffline checks skipped: respx is not installed")
        return

    print("\n=== Offline: tags with different timestamps (gaps)")
    body = [
        record("A", 0, 1.5),
        record("A", 2, 3.5),
        record("B", 1, 20.5),
        record("B", 2, 30.5),
        record("C", 3, 400.5),
    ]
    df = mock_read(body, ["A", "B", "C"], OutputFormat.DATAFRAME)
    print(df)
    assert isinstance(df, pd.DataFrame)
    check("one row per timestamp", len(df) == 4, f"{len(df)} rows")
    check("values not shifted", df.loc["2025-01-01 00:02:00", "B"] == 30.5)
    check("NaN where a tag has no value", pd.isna(df.loc["2025-01-01 00:01:00", "A"]))
    records = mock_read(body, ["A", "B", "C"], OutputFormat.JSON)
    check("JSON has one record per value", len(records) == len(body), f"{len(records)} records")

    print("\n=== Offline: integer values in JSON output")
    body = [record("A", 0, 1), record("A", 1, 2)]
    records = mock_read(body, ["A"], OutputFormat.JSON)
    print(records)
    check("integer values returned", [r["value"] for r in records] == [1, 2])
    check("values are Python types", all(type(r["value"]) is int for r in records))

    print("\n=== Offline: two values of one tag at the same timestamp")
    body = [record("A", 0, 1), record("A", 0, 2), record("B", 1, 20)]
    df = mock_read(body, ["A", "B"], OutputFormat.DATAFRAME)
    print(df)
    assert isinstance(df, pd.DataFrame)
    check("both values kept", df["A"].dropna().tolist() == [1, 2])
    check("other tag not repeated", df["B"].dropna().tolist() == [20])

    print("\n=== Offline: duplicate timestamp in one tag, single value in the other")
    body = [record("A", 0, 1), record("A", 0, 2), record("B", 0, 20)]
    df = mock_read(body, ["A", "B"], OutputFormat.DATAFRAME)
    print(df)
    assert isinstance(df, pd.DataFrame)
    check("both values of A kept", df["A"].tolist() == [1, 2])
    check("B appears once", df["B"].dropna().tolist() == [20])


def live_read(base_url: str, tags: list[str], start: str, end: str) -> tuple[pd.DataFrame, list]:
    """Read the tags as a DataFrame and as JSON."""
    username, password = os.getenv("ASPEN_USERNAME"), os.getenv("ASPEN_PASSWORD")
    with AspenClient(
        base_url,
        datasource=os.getenv("ASPEN_DATASOURCE") or None,
        auth=(username, password) if username and password else None,
        server_timezone=os.getenv("ASPEN_SERVER_TIMEZONE") or None,
        verify_ssl=os.getenv("ASPEN_VERIFY_SSL", "True").lower() == "true",
    ) as client:
        df = client.read(
            tags, start=start, end=end, read_type=ReaderType.RAW, output=OutputFormat.DATAFRAME
        )
        records = client.read(
            tags, start=start, end=end, read_type=ReaderType.RAW, output=OutputFormat.JSON
        )
    assert isinstance(df, pd.DataFrame)
    assert isinstance(records, list)
    return df, records


def run_live(hours: float) -> None:
    base_url = os.getenv("ASPEN_BASE_URL")
    tags = [t.strip() for t in os.getenv("ASPEN_TEST_TAGS", "").split(",") if t.strip()]
    if not base_url or not tags:
        print("\nLive check skipped: set ASPEN_BASE_URL and ASPEN_TEST_TAGS in .env")
        return

    end = datetime.now().replace(microsecond=0)
    start = end - timedelta(hours=hours)
    print(f"\n=== Live: RAW read of {tags}, {start} to {end}")

    try:
        df, records = live_read(base_url, tags, str(start), str(end))
    except httpx.HTTPError as e:
        check("live read", False, f"{type(e).__name__}: {e}")
        return

    print(df.head(10))
    print(f"... {len(df)} rows, {len(records)} JSON records")
    check("data returned", len(df) > 0)
    check("time index sorted", df.index.is_monotonic_increasing)

    for tag in tags:
        if tag not in df.columns:
            print(f"  [INFO] {tag}: no data")
            continue
        values = df[tag].dropna()
        tag_records = [r for r in records if r["tag"] == tag]
        duplicates = int(values.index.duplicated().sum())
        print(
            f"  [INFO] {tag}: {len(values)} values, {len(df) - len(values)} gaps, "
            f"{duplicates} duplicate timestamps"
        )
        check(f"{tag}: JSON has every DataFrame value", len(tag_records) == len(values))
        check(
            f"{tag}: JSON values match",
            [r["value"] for r in tag_records] == values.tolist(),
        )
        check(
            f"{tag}: JSON values are Python types",
            all(type(r["value"]) in (int, float, str) for r in tag_records),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hours", type=float, default=1.0, help="live read span (default 1)")
    args = parser.parse_args()

    run_offline()
    run_live(args.hours)

    print(f"\n{'All checks passed' if not failures else f'{len(failures)} check(s) failed'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
