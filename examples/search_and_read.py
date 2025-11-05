"""Example script demonstrating how to search for tags and read their data."""

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from aspy21 import AspenClient, ReaderType, configure_logging

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
        # Example 1: Search and read with return_desc=False (recommended)
        print("Example 1: Search for tags and read their data (return_desc=False)")
        print("-" * 80)
        print("Searching for temperature tags...")

        # Get list of tag names matching pattern
        tag_names_result = client.search(tag="TEMP*", return_desc=False, max_results=5)
        # Type narrowing: return_desc=False guarantees list[str]
        assert isinstance(tag_names_result, list) and (
            not tag_names_result or isinstance(tag_names_result[0], str)
        )
        tag_names: list[str] = tag_names_result  # type: ignore[assignment]
        print(f"Found {len(tag_names)} tags: {tag_names}")

        if tag_names:
            print("\nReading last hour of data...")
            result = client.read(
                tags=tag_names,
                start="2025-01-31 08:00:00",
                end="2025-01-31 09:00:00",
                read_type=ReaderType.RAW,
                as_df=True,
            )
            # Type narrowing: as_df=True guarantees pd.DataFrame
            assert isinstance(result, pd.DataFrame)
            df: pd.DataFrame = result

            print(f"Data shape: {df.shape}")
            print(f"\nFirst few rows:\n{df.head()}")
        print()

        # Example 2: Search with descriptions, then extract names
        print("Example 2: Search with descriptions, then extract names")
        print("-" * 80)
        print("Searching for reactor tags...")

        # Get tags with descriptions for display/logging
        tags_result = client.search(tag="*", description="reactor", max_results=5)
        # Type narrowing: return_desc=True (default) guarantees list[dict[str, str]]
        assert isinstance(tags_result, list) and (
            not tags_result or isinstance(tags_result[0], dict)
        )
        tags: list[dict[str, str]] = tags_result  # type: ignore[assignment]

        print(f"Found {len(tags)} tags:")
        for tag in tags:
            print(f"  - {tag['name']:30} : {tag['description']}")

        if tags:
            # Extract just the names for reading
            tag_names_list = [tag["name"] for tag in tags]

            print("\nReading 10-minute averages...")
            result = client.read(
                tags=tag_names_list,
                start="2025-01-31 08:00:00",
                end="2025-01-31 09:00:00",
                read_type=ReaderType.AVG,
                interval=600,  # 10 minute averages
                as_df=True,
            )
            # Type narrowing: as_df=True guarantees pd.DataFrame
            assert isinstance(result, pd.DataFrame)
            df: pd.DataFrame = result

            print(f"Data shape: {df.shape}")
            print(f"\nFirst few rows:\n{df.head()}")
        print()

        # Example 3: Search by description only
        print("Example 3: Search by description and read data")
        print("-" * 80)
        print("Searching for all V1-01 tags...")

        # Find all tags related to V1-01
        tag_names_result2 = client.search(description="V1-01", return_desc=False, max_results=10)
        # Type narrowing: return_desc=False guarantees list[str]
        assert isinstance(tag_names_result2, list) and (
            not tag_names_result2 or isinstance(tag_names_result2[0], str)
        )
        tag_names_v101: list[str] = tag_names_result2  # type: ignore[assignment]
        print(f"Found {len(tag_names_v101)} tags: {tag_names_v101[:5]}...")

        if tag_names_v101:
            print("\nReading hourly averages...")
            result = client.read(
                tags=tag_names_v101[:5],  # Limit to first 5 tags for demo
                start="2025-01-31 00:00:00",
                end="2025-01-31 12:00:00",
                read_type=ReaderType.AVG,
                interval=3600,  # 1 hour averages
                as_df=True,
            )
            # Type narrowing: as_df=True guarantees pd.DataFrame
            assert isinstance(result, pd.DataFrame)
            df: pd.DataFrame = result

            print(f"Data shape: {df.shape}")
            print(f"\nFirst few rows:\n{df.head()}")
        print()

        # Example 4: Filter and select specific tags
        print("Example 4: Search broadly, filter, then read")
        print("-" * 80)
        print("Searching for all G* tags with V1-01 in description...")

        # Search broadly
        all_tags_result = client.search(tag="G*", description="V1-01", max_results=20)
        # Type narrowing: return_desc=True (default) guarantees list[dict[str, str]]
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
                tags=selected_tags[:3],  # Limit to first 3 for demo
                start="2025-01-31 08:00:00",
                end="2025-01-31 09:00:00",
                read_type=ReaderType.RAW,
                as_df=True,
            )
            # Type narrowing: as_df=True guarantees pd.DataFrame
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
