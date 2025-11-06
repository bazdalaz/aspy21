"""Example script demonstrating how to search for tags and read their data."""

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from aspy21 import AspenClient, IncludeFields, OutputFormat, ReaderType, configure_logging

# Load .env from project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Configure logging from ASPEN_LOG_LEVEL environment variable
configure_logging()


print("\n" + "=" * 80)
print("Search and Read Example")
print("=" * 80 + "\n")

# Get configuration from environment
base_url = os.getenv("ASPEN_BASE_URL")
username = os.getenv("ASPEN_USERNAME")
password = os.getenv("ASPEN_PASSWORD")
datasource = os.getenv("ASPEN_DATASOURCE", "")

# Validate required variables
if not all([base_url, username, password, datasource]):
    print("ERROR: Missing required environment variables!")
    print("Required: ASPEN_BASE_URL, ASPEN_USERNAME, ASPEN_PASSWORD, ASPEN_DATASOURCE")
    print("Please create .env file from .env.example")
    exit(1)

# Type narrowing: assert non-None after validation
assert base_url is not None
assert username is not None
assert password is not None

# Create client using context manager
try:
    with AspenClient(
        base_url=base_url,
        auth=(username, password),
        datasource=datasource,
    ) as client:
        # Example 1: Search and read separately
        print("Example 1: Search for tags and read their data separately")
        print("-" * 80)
        print("Searching for temperature tags...")

        # Get list of tag names matching pattern (default include=NONE returns list[str])
        tag_names_result = client.search("TEMP*", limit=5)
        # Type narrowing: include=NONE guarantees list[str]
        assert isinstance(tag_names_result, list) and (
            not tag_names_result or isinstance(tag_names_result[0], str)
        )
        tag_names: list[str] = tag_names_result  # type: ignore[assignment]
        print(f"Found {len(tag_names)} tags: {tag_names}")

        if tag_names:
            print("\nReading last hour of data...")
            result = client.read(
                tag_names,
                start="2025-01-31 08:00:00",
                end="2025-01-31 09:00:00",
                read_type=ReaderType.RAW,
                output=OutputFormat.DATAFRAME,
            )
            # Type narrowing: output=DATAFRAME guarantees pd.DataFrame
            assert isinstance(result, pd.DataFrame)
            df: pd.DataFrame = result

            print(f"Data shape: {df.shape}")
            print(f"\nFirst few rows:\n{df.head()}")
        print()

        # Example 2: Hybrid mode - search and read in one call
        print("Example 2: Hybrid mode - search and read in one call")
        print("-" * 80)
        print("Searching for reactor tags and reading their data...")

        # Use hybrid mode: search + read in single call
        result = client.search(
            description="reactor",
            limit=5,
            start="2025-01-31 08:00:00",
            end="2025-01-31 09:00:00",
            read_type=ReaderType.AVG,
            interval=600,  # 10 minute averages
            output=OutputFormat.DATAFRAME,
        )
        # Type narrowing: output=DATAFRAME guarantees pd.DataFrame
        assert isinstance(result, pd.DataFrame)
        df: pd.DataFrame = result

        if not df.empty:
            print(f"Data shape: {df.shape}")
            print(f"\nFirst few rows:\n{df.head()}")
        else:
            print("No data found")
        print()

        # Example 3: Hybrid mode with description search
        print("Example 3: Hybrid mode with description search")
        print("-" * 80)
        print("Searching for V1-01 tags and reading hourly averages...")

        # Use hybrid mode with description search
        result = client.search(
            description="V1-01",
            limit=5,
            start="2025-01-31 00:00:00",
            end="2025-01-31 12:00:00",
            read_type=ReaderType.AVG,
            interval=3600,  # 1 hour averages
            output=OutputFormat.DATAFRAME,
        )
        # Type narrowing: output=DATAFRAME guarantees pd.DataFrame
        assert isinstance(result, pd.DataFrame)
        df: pd.DataFrame = result

        if not df.empty:
            print(f"Data shape: {df.shape}")
            print(f"\nFirst few rows:\n{df.head()}")
        else:
            print("No data found")
        print()

        # Example 4: Search with descriptions, filter, then read
        print("Example 4: Search broadly, filter, then read")
        print("-" * 80)
        print("Searching for all G* tags with V1-01 in description...")

        # Search broadly and get descriptions
        all_tags_result = client.search(
            "G*", description="V1-01", limit=20, include=IncludeFields.DESCRIPTION
        )
        # Type narrowing: include=DESCRIPTION guarantees list[dict[str, str]]
        assert isinstance(all_tags_result, list) and (
            not all_tags_result or isinstance(all_tags_result[0], dict)
        )
        all_tags: list[dict[str, str]] = all_tags_result  # type: ignore[assignment]
        print(f"Found {len(all_tags)} tags total")

        # Filter to only temperature and pressure tags
        selected_tags = [
            tag["name"]
            for tag in all_tags
            if "TEMP" in tag["name"].upper() or "PRESS" in tag["name"].upper()
        ]

        print(f"Filtered to {len(selected_tags)} temperature/pressure tags:")
        for tag_name in selected_tags[:5]:
            print(f"  - {tag_name}")

        if selected_tags:
            print("\nReading raw data...")
            result = client.read(
                selected_tags[:3],  # Limit to first 3 for demo
                start="2025-01-31 08:00:00",
                end="2025-01-31 09:00:00",
                read_type=ReaderType.RAW,
                output=OutputFormat.DATAFRAME,
            )
            # Type narrowing: output=DATAFRAME guarantees pd.DataFrame
            assert isinstance(result, pd.DataFrame)
            df: pd.DataFrame = result

            print(f"Data shape: {df.shape}")
            print(f"\nFirst few rows:\n{df.head()}")
        print()

        print("=" * 80)
        print("Examples completed successfully!")
        print("=" * 80)

    # Connection automatically closed here

except Exception as e:
    print("\n" + "=" * 80)
    print("ERROR!")
    print("=" * 80)
    print(f"\n{type(e).__name__}: {e}\n")
    import traceback

    traceback.print_exc()

print("Done.\n")
