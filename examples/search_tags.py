"""Example script demonstrating tag search functionality."""

import os
from pathlib import Path

from dotenv import load_dotenv

from aspy21 import AspenClient, configure_logging

# Load .env from project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Configure logging from ASPEN_LOG_LEVEL environment variable
configure_logging()


print("\n" + "=" * 80)
print("Tag Search Examples")
print("=" * 80 + "\n")

# Get configuration from environment
base_url = os.getenv("ASPEN_BASE_URL")
username = os.getenv("ASPEN_USERNAME")
password = os.getenv("ASPEN_PASSWORD")
datasource = os.getenv("ASPEN_DATASOURCE", "")

# Validate required variables
if not all([base_url, username, password]):
    print("ERROR: Missing required environment variables!")
    print("Required: ASPEN_BASE_URL, ASPEN_USERNAME, ASPEN_PASSWORD")
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
        # Example 1: Search by tag name pattern with wildcards
        print("Example 1: Search all tags starting with 'TEMP'")
        print("-" * 80)
        tags_raw = client.search(tag="TEMP*", max_results=10)
        # Type narrowing: return_desc=True (default) guarantees list[dict[str, str]]
        assert isinstance(tags_raw, list) and (not tags_raw or isinstance(tags_raw[0], dict))
        tags: list[dict[str, str]] = tags_raw  # type: ignore[assignment]
        print(f"Found {len(tags)} tags:\n")
        for tag in tags[:5]:  # Show first 5
            print(f"  {tag['name']:30} - {tag['description']}")
        print()

        # Example 2: Search by description only (uses SQL endpoint)
        print("Example 2: Search all tags with description containing 'V1-01'")
        print("-" * 80)
        tags_raw = client.search(description="V1-01", max_results=10)
        # Type narrowing: return_desc=True (default) guarantees list[dict[str, str]]
        assert isinstance(tags_raw, list) and (not tags_raw or isinstance(tags_raw[0], dict))
        tags: list[dict[str, str]] = tags_raw  # type: ignore[assignment]
        print(f"Found {len(tags)} tags:\n")
        for tag in tags[:5]:
            print(f"  {tag['name']:30} - {tag['description']}")
        print()

        # Example 3: Combine tag pattern and description
        print("Example 3: Search 'AI*' tags with 'temperature' in description")
        print("-" * 80)
        tags_raw = client.search(tag="AI*", description="temperature", max_results=10)
        # Type narrowing: return_desc=True (default) guarantees list[dict[str, str]]
        assert isinstance(tags_raw, list) and (not tags_raw or isinstance(tags_raw[0], dict))
        tags: list[dict[str, str]] = tags_raw  # type: ignore[assignment]
        print(f"Found {len(tags)} tags:\n")
        for tag in tags[:5]:
            print(f"  {tag['name']:30} - {tag['description']}")
        print()

        # Example 4: Wildcard examples
        print("Example 4: Using wildcards")
        print("-" * 80)
        print("  '*'       - matches all tags")
        print("  '*FLOW*'  - matches tags containing FLOW anywhere")
        print("  'AI_10?'  - matches AI_101, AI_102, etc. (? = single char)")
        print("  'TEMP_*'  - matches all tags starting with TEMP_")
        print()

        # Example 5: Case-insensitive search (default)
        print("Example 5: Case-insensitive search (lowercase query)")
        print("-" * 80)
        tags_raw = client.search(tag="*", description="reactor", max_results=5)
        # Type narrowing: return_desc=True (default) guarantees list[dict[str, str]]
        assert isinstance(tags_raw, list) and (not tags_raw or isinstance(tags_raw[0], dict))
        tags: list[dict[str, str]] = tags_raw  # type: ignore[assignment]
        print(f"Found {len(tags)} tags (matches 'Reactor', 'REACTOR', etc.):\n")
        for tag in tags[:5]:
            print(f"  {tag['name']:30} - {tag['description']}")
        print()

        print("=" * 80)
        print("Search examples completed successfully!")
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
