"""Example script testing Basic Auth (works on Linux/Mac/Windows)."""

import os
from pathlib import Path

from dotenv import load_dotenv

from aspy21 import AspenClient, ReaderType, configure_logging

# Load .env from project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Configure logging from ASPEN_LOG_LEVEL environment variable
configure_logging()


print("\n" + "=" * 80)
print("Testing Basic Authentication (Linux/Mac/Windows Compatible)")
print("=" * 80 + "\n")

# Get configuration from environment
base_url = os.getenv("ASPEN_BASE_URL")
username = os.getenv("ASPEN_USERNAME")
password = os.getenv("ASPEN_PASSWORD")
datasource = os.getenv("ASPEN_DATASOURCE", "")
timeout = float(os.getenv("ASPEN_TIMEOUT", "60.0"))
verify_ssl = os.getenv("ASPEN_VERIFY_SSL", "False").lower() == "true"

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

print(f"Base URL: {base_url}")
print(f"Username: {username}")
print(f"Datasource: {datasource or '(server default)'}\n")

# Basic Auth - works on all platforms
# Using context manager (recommended) - automatically closes connection
print("Client initialized with Basic Auth\n")

try:
    # Replace with your actual tag name
    test_tag = "YOUR_TAG_NAME"
    print(f"Reading tag: {test_tag}")
    print("Time range: 2025-06-20T08:00:00 to 2025-06-20T09:00:00\n")

    # Using 'with' statement ensures connection is properly closed
    with AspenClient(
        base_url=base_url,
        auth=(username, password),
        datasource=datasource,
        timeout=timeout,
        verify_ssl=verify_ssl,
    ) as client:
        df = client.read(
            tags=[test_tag],
            start="2025-06-20T08:00:00",
            end="2025-06-20T09:00:00",
            read_type=ReaderType.RAW,
        )

        print("\n" + "=" * 80)
        print("SUCCESS - Data retrieved!")
        print("=" * 80)
        print(f"\nRetrieved {len(df)} rows:\n")
        print(df)
        print()

    # Connection automatically closed here

except Exception as e:
    print("\n" + "=" * 80)
    print("ERROR!")
    print("=" * 80)
    print(f"\n{type(e).__name__}: {e}\n")
    import traceback

    traceback.print_exc()

print("Done.\n")
