"""Smoke test for the SQL/XML escaping fix against a real IP.21 server.

Reads connection settings from .env in the project root, the same way as
examples/basic_usage.py (see .env.example). The first tag in ASPEN_TEST_TAGS
is used for the read checks.

Usage:
    pip install ".[examples]"
    python scripts/smoke_test.py
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

import aspy21
from aspy21 import AspenClient, ReaderType, configure_logging, query_builder

# Fail fast if an older aspy21 (e.g. from PyPI) is installed instead of this checkout
if not hasattr(query_builder, "sql_literal"):
    print(f"ERROR: aspy21 {aspy21.__version__} at {aspy21.__file__}")
    print("does not include the escaping fix. Install this checkout with: pip install -e .")
    exit(1)

# Load .env from project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Configure logging from ASPEN_LOG_LEVEL environment variable
configure_logging()

# Get configuration from environment
base_url = os.getenv("ASPEN_BASE_URL")
username = os.getenv("ASPEN_USERNAME")
password = os.getenv("ASPEN_PASSWORD")
datasource = os.getenv("ASPEN_DATASOURCE", "")
timeout = float(os.getenv("ASPEN_TIMEOUT", "60.0"))
test_tags = [t.strip() for t in os.getenv("ASPEN_TEST_TAGS", "").split(",") if t.strip()]
verify_ssl = os.getenv("ASPEN_VERIFY_SSL", "False").lower() == "true"

# Validate required variables
if not all([base_url, username, password, datasource, test_tags]):
    print("ERROR: Missing required environment variables!")
    print(
        "Required: ASPEN_BASE_URL, ASPEN_USERNAME, ASPEN_PASSWORD, "
        "ASPEN_DATASOURCE, ASPEN_TEST_TAGS"
    )
    print(f"Looked for .env at: {env_path}")
    exit(1)

# Type narrowing: assert non-None after validation
assert base_url is not None
assert username is not None
assert password is not None

print(f"aspy21 {aspy21.__version__} from {aspy21.__file__}")
print(f"Base URL: {base_url}")
print(f"Datasource: {datasource}")
print(f"Tag: {test_tags[0]}\n")

tag = test_tags[0]
end = datetime.now() - timedelta(hours=1)
start = end - timedelta(hours=1)


def raw_sql(client: AspenClient, sql: str) -> str:
    """Send SQL directly to the SQL endpoint and return the raw response text."""
    xml = (
        f'<SQL g="aspy21_smoke" t="SQLplus" ds={query_builder.xml_attr(datasource)} '
        f'dso="CHARINT=N;CHARFLOAT=N;CHARTIME=N;CONVERTERRORS=N" '
        f'm="5" to="30" response="Record" s="1">'
        f"{query_builder.cdata(sql)}</SQL>"
    )
    response = client._client.post(
        f"{client.base_url}/SQL", content=xml, headers={"Content-Type": "text/xml"}
    )
    response.raise_for_status()
    return response.text[:500]


def quote_round_trip(client: AspenClient) -> str:
    """Select an escaped literal; the server must return it with a single quote."""
    literal = query_builder.sql_literal("O'Brien")
    sql = f"Select name, {literal} q from all_records where name = {query_builder.sql_literal(tag)}"
    text = raw_sql(client, sql)
    if "O'Brien" not in text:
        raise AssertionError(f"'O''Brien' did not come back as O'Brien. Raw response: {text}")
    return text


with AspenClient(
    base_url=base_url,
    auth=(username, password),
    datasource=datasource,
    timeout=timeout,
    verify_ssl=verify_ssl,
) as c:
    checks = {
        "escaped quote round-trip (escaping)": lambda: quote_round_trip(c),
        "broken quote, raw response (control)": lambda: raw_sql(
            c, f"Select name from all_records where name = 'O'Brien' or name = '{tag}'"
        ),
        "browse search": lambda: c.search(tag=tag[:3] + "*", limit=5),
        "description search": lambda: c.search(description="temp", limit=5),
        "quote in description (escaping)": lambda: c.search(description="O'Brien", limit=5),
        "quote in tag pattern (escaping)": lambda: c.search(tag="X'*", description="temp", limit=5),
        "history read (INT)": lambda: c.read(
            [tag], start=start.isoformat(), end=end.isoformat(), interval=600
        )[:3],
        "snapshot read": lambda: c.read([tag]),
        "aggregate read (AVG)": lambda: c.read(
            [tag], start=start.isoformat(), end=end.isoformat(), read_type=ReaderType.AVG
        ),
    }
    failed = 0
    for name, fn in checks.items():
        try:
            print(f"OK    {name}: {fn()}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")

print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
