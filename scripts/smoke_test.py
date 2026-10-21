"""Smoke test for the SQL/XML escaping fix against a real IP.21 server.

Reads connection settings from .env in the project root, the same way as
examples/basic_usage.py (see .env.example). The first tag in ASPEN_TEST_TAGS
is used for the read checks.

Usage:
    pip install ".[examples]"
    python scripts/smoke_test.py
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

import aspy21
from aspy21 import AspenClient, AspenSqlError, ReaderType, configure_logging, query_builder
from aspy21.errors import raise_for_sql_error

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


def raw_sql(client: AspenClient, sql: str, mode: str = "Record") -> str:
    """Send SQL directly to the SQL endpoint and return the raw response text."""
    xml = (
        f'<SQL g="aspy21_smoke" t="SQLplus" ds={query_builder.xml_attr(datasource)} '
        f'dso="CHARINT=N;CHARFLOAT=N;CHARTIME=N;CONVERTERRORS=N" '
        f'm="5" to="30" response="{mode}" s="1">'
        f"{query_builder.cdata(sql)}</SQL>"
    )
    response = client._client.post(
        f"{client.base_url}/SQL", content=xml, headers={"Content-Type": "text/xml"}
    )
    response.raise_for_status()
    return response.text


def round_trip(client: AspenClient, value: str) -> str:
    """Select an escaped literal; the server must return exactly the original value."""
    literal = query_builder.sql_literal(value)
    sql = f"Select name, {literal} q from all_records where name = {query_builder.sql_literal(tag)}"
    text = raw_sql(client, sql)
    records = json.loads(text) if text.startswith("[") else []
    if not records or records[0].get("q") != value:
        raise AssertionError(f"{literal} did not come back as {value!r}. Raw response: {text}")
    return text


# Read-only injection payload: if it escaped the literal, it would match every record
INJECTION = "zzz_no_such_text' or name like '%"


def injection_control(client: AspenClient) -> str:
    """Send the payload UNESCAPED (as aspy21 0.0.4 did) to show it would return rows."""
    sql = f"Select name from all_records where name->ip_description like '%{INJECTION}%'"
    text = raw_sql(client, sql)
    if '"name"' not in text:
        raise AssertionError(f"Unescaped payload returned no rows, control is invalid: {text}")
    return text


def sql_error_detected(client: AspenClient, mode: str) -> str:
    """Send invalid SQL; aspy21 must recognize the server's error response."""
    text = raw_sql(client, "Select name from all_records where name = 'O'Brien'", mode)
    try:
        raise_for_sql_error(json.loads(text))
    except AspenSqlError as e:
        return f"{e} | raw: {text[:300]}"
    raise AssertionError(f"Error response not recognized. Raw response: {text[:500]}")


def expect_empty(result: object) -> object:
    if result:
        raise AssertionError(f"Injection returned data: {result}")
    return result


with AspenClient(
    base_url=base_url,
    auth=(username, password),
    datasource=datasource,
    timeout=timeout,
    verify_ssl=verify_ssl,
) as c:
    checks = {
        "escaped quote round-trip (escaping)": lambda: round_trip(c, "O'Brien"),
        "backslash-quote round-trip (escaping)": lambda: round_trip(c, "x\\'y\\"),
        "unescaped payload returns rows (injection control)": lambda: injection_control(c),
        "payload via search description (injection)": lambda: expect_empty(
            c.search(description=INJECTION, limit=5)
        ),
        "payload via search tag pattern (injection)": lambda: expect_empty(
            c.search(tag=INJECTION, description="a", limit=5)
        ),
        "payload via snapshot read (injection)": lambda: expect_empty(c.read([INJECTION])),
        "payload via history read (injection)": lambda: expect_empty(
            c.read([INJECTION], start=start.isoformat(), end=end.isoformat(), interval=600)
        ),
        "SQL error detected, Record format (errors)": lambda: sql_error_detected(c, "Record"),
        "SQL error detected, Original format (errors)": lambda: sql_error_detected(c, "Original"),
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
