"""Smoke test against a real IP.21 server: escaping, SQL errors, time zones and retries.

Reads connection settings from .env in the project root, the same way as
examples/basic_usage.py (see .env.example). The first tag in ASPEN_TEST_TAGS
is used for the read checks; the last one for the aggregate checks (use a numeric tag,
e.g. ASPEN_TEST_TAGS=GXV1255.PV,CTI4551.PV).

The retry checks put a transport in front of the server that fails the first requests
(HTTP 503 or a connection error) before forwarding the rest, so the server only ever
receives the same read-only requests as the other checks.

Usage:
    pip install ".[examples]"
    python scripts/smoke_test.py
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

import aspy21
from aspy21 import (
    AspenClient,
    AspenSqlError,
    ReaderType,
    configure_logging,
    query_builder,
    utils,
)
from aspy21.errors import raise_for_sql_error

# Fail fast if an older aspy21 (e.g. from PyPI) is installed instead of this checkout
if (
    not hasattr(query_builder, "sql_literal")
    or not hasattr(utils, "server_now")
    or not hasattr(aspy21, "retry")
):
    print(f"ERROR: aspy21 {aspy21.__version__} at {aspy21.__file__}")
    print("does not include the escaping, timezone and retry changes.")
    print("Install this checkout with: pip install -e .")
    sys.exit(1)

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
server_timezone = os.getenv("ASPEN_SERVER_TIMEZONE") or None

# Validate required variables
if not all([base_url, username, password, datasource, test_tags]):
    print("ERROR: Missing required environment variables!")
    print(
        "Required: ASPEN_BASE_URL, ASPEN_USERNAME, ASPEN_PASSWORD, "
        "ASPEN_DATASOURCE, ASPEN_TEST_TAGS"
    )
    print(f"Looked for .env at: {env_path}")
    sys.exit(1)

try:
    utils.check_timezone(server_timezone)
except ValueError as e:
    print(f"ERROR: {e}. Use an IANA name such as Europe/Berlin, or leave it unset.")
    sys.exit(1)

# Type narrowing: assert non-None after validation
assert base_url is not None
assert username is not None
assert password is not None

print(f"aspy21 {aspy21.__version__} from {aspy21.__file__}")
print(f"Base URL: {base_url}")
print(f"Datasource: {datasource}")
print(f"Tag: {test_tags[0]}")
print(f"Aggregate tag (last in ASPEN_TEST_TAGS, use a numeric tag): {test_tags[-1]}")
print(f"Server timezone (ASPEN_SERVER_TIMEZONE): {server_timezone or 'not set, naive'}\n")

tag = test_tags[0]
agg_tag = test_tags[-1]
# Server local time, as IP.21 interprets query timestamps
end = utils.server_now(server_timezone).to_pydatetime() - timedelta(hours=1)
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


def timezone_diagnostics(client: AspenClient) -> None:
    """Print raw server timestamps next to this machine's clock (read-only, never fails)."""
    now = datetime.now().astimezone()
    print("Timezone diagnostics")
    print(f"  local now: {now.isoformat()} ({now.tzname()})")
    print(f"  utc now:   {now.astimezone(timezone.utc).isoformat()}")
    w_start = query_builder.sql_timestamp(str(start))
    w_end = query_builder.sql_timestamp(str(start + timedelta(minutes=10)))
    window = f"ts between '{w_start}' and '{w_end}'"
    name = query_builder.sql_literal(tag)
    queries = {
        "history ts": f"Select ts, name, value from history(80) where name={name} "
        f"and {window} and request=1 and period=3000",
        "input time": f"Select name, name->ip_input_time t, name->ip_input_value v "
        f"from all_records where name={name}",
        "db time": f"Select name, getdbtime t from all_records where name={name}",
    }
    print(f"  requested window: {w_start} to {w_end} (sent as local time)")
    for label, sql in queries.items():
        try:
            print(f"  {label}: {raw_sql(client, sql)[:400]}")
        except Exception as e:
            print(f"  {label}: {type(e).__name__}: {e}")
    print()


class FlakyTransport(httpx.BaseTransport):
    """Fail the first `fail` requests, then forward the rest to the real server."""

    def __init__(self, fail: int, error: str = "503") -> None:
        self.fail = fail
        self.error = error
        self.attempts = 0  # requests aspy21 sent, failed or forwarded
        self.forwarded = 0  # requests that reached the server
        self.real = httpx.HTTPTransport(verify=verify_ssl)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        if self.attempts <= self.fail:
            if self.error == "connect":
                raise httpx.ConnectError("injected by smoke test", request=request)
            return httpx.Response(503, request=request)
        self.forwarded += 1
        return self.real.handle_request(request)


class RetryLog(logging.Handler):
    """Collect aspy21 retry warnings, whatever ASPEN_LOG_LEVEL is set to."""

    def __enter__(self) -> list[str]:
        self.messages: list[str] = []
        self.logger = logging.getLogger("aspy21.retry")
        self.old_level = self.logger.level
        self.logger.setLevel(logging.WARNING)
        self.logger.addHandler(self)
        return self.messages

    def __exit__(self, *exc: object) -> None:
        self.logger.removeHandler(self)
        self.logger.setLevel(self.old_level)

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def flaky_client(transport: httpx.BaseTransport, **kwargs) -> AspenClient:
    http = httpx.Client(transport=transport, auth=(username, password), timeout=timeout)
    return AspenClient(base_url, datasource=datasource, http_client=http, **kwargs)


def retry_recovers(fail: int, error: str, operation: str) -> str:
    """Fail `fail` requests, then expect real data after exactly `fail` retries."""
    transport = FlakyTransport(fail, error)
    with RetryLog() as warnings, flaky_client(transport) as client:
        if operation == "search":
            result = client.search(tag=tag[:3] + "*", limit=5)
        else:
            result = client.read([tag])
    if not result:
        raise AssertionError("No data after retries")
    if len(warnings) != fail or transport.forwarded != 1:
        raise AssertionError(
            f"Expected {fail} retries and 1 request to the server, got {len(warnings)} "
            f"retries and {transport.forwarded} requests: {warnings}"
        )
    return f"{warnings} -> {result}"


def retry_gives_up(fail: int, retries: int) -> str:
    """Fail every attempt; expect the 503 to be raised after `retries` retries."""
    transport = FlakyTransport(fail)
    with RetryLog() as warnings, flaky_client(transport, retries=retries) as client:
        try:
            client.read([tag])
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 503:
                raise
        else:
            raise AssertionError("Read succeeded although every attempt failed")
    if transport.attempts != retries + 1 or len(warnings) != retries or transport.forwarded:
        raise AssertionError(
            f"Expected {retries + 1} attempts and none forwarded, got {transport.attempts} "
            f"attempts, {transport.forwarded} forwarded: {warnings}"
        )
    return f"HTTPStatusError 503 after {transport.attempts} attempt(s): {warnings}"


def retry_unreachable() -> str:
    """A refused connection on this machine: retried, then ConnectError (no server contact)."""
    began = time.monotonic()
    with RetryLog() as warnings:
        http = httpx.Client(timeout=5)
        with AspenClient(
            "http://127.0.0.1:1/ProcessData", datasource=datasource, http_client=http
        ) as client:
            try:
                client.read([tag])
            except httpx.ConnectError:
                pass
            else:
                raise AssertionError("Read succeeded against a closed port")
    elapsed = time.monotonic() - began
    if len(warnings) != 2 or elapsed < 1.5:
        raise AssertionError(f"Expected 2 retries over >=1.5s, got {warnings} in {elapsed:.1f}s")
    return f"ConnectError after {elapsed:.1f}s: {warnings}"


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
    server_timezone=server_timezone,
) as c:
    timezone_diagnostics(c)
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
            [agg_tag], start=start.isoformat(), end=end.isoformat(), read_type=ReaderType.AVG
        ),
        "aggregate read (AVG, 10 min interval)": lambda: c.read(
            [agg_tag],
            start=start.isoformat(),
            end=end.isoformat(),
            read_type=ReaderType.AVG,
            interval=600,
        ),
        "2 x 503, then data (retries)": lambda: retry_recovers(2, "503", "read"),
        "connection error, then data (retries)": lambda: retry_recovers(1, "connect", "read"),
        "503 on browse search, then data (retries)": lambda: retry_recovers(1, "503", "search"),
        "503 on every attempt, gives up after 3 (retries)": lambda: retry_gives_up(3, 2),
        "retries=0 fails on first 503 (retries)": lambda: retry_gives_up(1, 0),
        "closed local port, retried then ConnectError (retries)": retry_unreachable,
    }
    failed = 0
    for name, fn in checks.items():
        try:
            print(f"OK    {name}: {fn()}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")

print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
