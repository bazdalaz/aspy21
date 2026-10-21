"""SQL injection tests for every user-controlled value that reaches a SQLplus query.

Each test builds a query twice: once with a harmless value and once with an attack
payload in the same slot. After replacing every string literal with "?", both queries
must have exactly the same structure, i.e. the payload stayed inside one literal.
"""

import xml.etree.ElementTree as ET

import httpx
import pytest

from aspy21 import AspenClient, ReaderType
from aspy21.query_builder import (
    SqlAggregatesQueryBuilder,
    SqlHistoryQueryBuilder,
    SqlSearchQueryBuilder,
    SqlSnapshotQueryBuilder,
)

PAYLOADS = [
    "x'; UPDATE ip_analogdef SET ip_description='pwned' WHERE name like '%'; --",
    "x'; DELETE FROM ip_analogdef; --",
    "x' UNION SELECT name FROM all_records --",
    "' or '1'='1",
    "x'' or ''1''=''1",
    "x'\nUPDATE ip_analogdef SET ip_input_value=0",
    "x' /* c */ or name like '%",
    "x'||'y",
    "x\\'; UPDATE ip_analogdef SET ip_input_value=0; --",
    "'",
    "''",
]

SAFE = "SAFE"


def split_literals(sql: str) -> tuple[str, list[str]]:
    """Split SQL into a skeleton (literals replaced by ?) and the decoded literals.

    Follows standard SQL: a literal is delimited by ' and '' inside it is one quote.
    """
    skeleton: list[str] = []
    literals: list[str] = []
    i = 0
    while i < len(sql):
        if sql[i] != "'":
            skeleton.append(sql[i])
            i += 1
            continue
        i += 1
        value: list[str] = []
        while True:
            if i >= len(sql):
                raise AssertionError(f"Unterminated string literal in: {sql}")
            if sql[i] == "'":
                if i + 1 < len(sql) and sql[i + 1] == "'":
                    value.append("'")
                    i += 2
                    continue
                i += 1
                break
            value.append(sql[i])
            i += 1
        skeleton.append("?")
        literals.append("".join(value))
    return "".join(skeleton), literals


def sql_of(xml: str) -> str:
    return ET.fromstring(xml).text or ""


def history(value: str) -> str:
    return sql_of(
        SqlHistoryQueryBuilder().build(
            [value, "T2"], "2025-01-01", "2025-01-02", "IP21", ReaderType.RAW
        )
    )


def history_single(value: str) -> str:
    return sql_of(
        SqlHistoryQueryBuilder().build(value, "2025-01-01", "2025-01-02", "IP21", ReaderType.INT)
    )


def snapshot(value: str) -> str:
    return sql_of(SqlSnapshotQueryBuilder().build(tags=[value, "T2"], datasource="IP21"))


def search_description(value: str) -> str:
    return sql_of(SqlSearchQueryBuilder().build(datasource="IP21", description=value))


def search_tag_pattern(value: str) -> str:
    return sql_of(
        SqlSearchQueryBuilder().build(datasource="IP21", description="temp", tag_pattern=value)
    )


def aggregates(field: str):
    def build(value: str) -> str:
        args = {"tags": ["T1"], "start": "2025-01-01", "end": "2025-01-02"}
        args[field] = [value] if field == "tags" else value
        return sql_of(
            SqlAggregatesQueryBuilder().build(
                datasource="IP21", read_type=ReaderType.AVG, interval=60, **args
            )
        )

    return build


# search() maps the user wildcards * and ? to SQL % and _
WILDCARDS = {"search description": {"*": "%"}, "search tag pattern": {"*": "%", "?": "_"}}

INPUTS = {
    "read tags (multi)": history,
    "read tags (single)": history_single,
    "snapshot tags": snapshot,
    "search description": search_description,
    "search tag pattern": search_tag_pattern,
    "aggregates tags": aggregates("tags"),
}


@pytest.mark.parametrize("payload", PAYLOADS)
@pytest.mark.parametrize("name", INPUTS.keys())
def test_payload_stays_inside_one_literal(name, payload):
    build = INPUTS[name]
    safe_skeleton, safe_literals = split_literals(build(SAFE))
    skeleton, literals = split_literals(build(payload))

    expected = payload
    for wildcard, sql_wildcard in WILDCARDS.get(name, {}).items():
        expected = expected.replace(wildcard, sql_wildcard)

    assert skeleton == safe_skeleton
    assert len(literals) == len(safe_literals)
    assert any(expected in literal for literal in literals)


XML_BREAKOUT = "x]]><SQL>UPDATE ip_analogdef SET ip_input_value=0</SQL>"


@pytest.mark.parametrize("name", [n for n in INPUTS if not n.startswith("aggregates")])
def test_cdata_terminator_is_rejected(name):
    with pytest.raises(ValueError, match=r"\]\]>"):
        INPUTS[name](XML_BREAKOUT)


@pytest.mark.parametrize("name", [n for n in INPUTS if n.startswith("aggregates")])
def test_aggregates_xml_breakout_stays_text(name):
    """The aggregates builder uses ElementTree, which escapes markup instead of CDATA."""
    skeleton, literals = split_literals(INPUTS[name](XML_BREAKOUT))

    assert "<SQL>" not in skeleton
    assert XML_BREAKOUT in literals


def history_timestamp(field: str):
    def build(value: str) -> str:
        args = {"start": "2025-01-01", "end": "2025-01-02"}
        args[field] = value
        return sql_of(
            SqlHistoryQueryBuilder().build(
                tags="T1", datasource="IP21", read_type=ReaderType.RAW, **args
            )
        )

    return build


TIMESTAMP_INPUTS = {
    "history start": history_timestamp("start"),
    "history end": history_timestamp("end"),
    "aggregates start": aggregates("start"),
    "aggregates end": aggregates("end"),
}


@pytest.mark.parametrize("payload", [*PAYLOADS, XML_BREAKOUT])
@pytest.mark.parametrize("name", TIMESTAMP_INPUTS.keys())
def test_timestamp_payload_is_rejected(name, payload):
    """Timestamps are parsed and re-formatted, so payloads never reach the query."""
    with pytest.raises(ValueError):
        TIMESTAMP_INPUTS[name](payload)


@pytest.mark.parametrize("payload", PAYLOADS)
def test_public_api_sends_payload_as_literal(mock_api, payload):
    """End to end: search() and read() put the payload inside a literal on the wire."""

    def respond(request: httpx.Request) -> httpx.Response:
        if b"aspy21_search" in request.content:
            return httpx.Response(200, json={"data": [{"rows": []}]})
        return httpx.Response(200, json=[])

    route = mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
        side_effect=respond
    )

    with AspenClient(
        base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll", datasource="IP21"
    ) as c:
        c.search(description=payload)
        c.read([payload], start="2025-01-01", end="2025-01-02")
        c.read([payload])

    for call in route.calls:
        sql = sql_of(call.request.content.decode())
        skeleton, literals = split_literals(sql)
        assert "UPDATE" not in skeleton.upper()
        assert "DELETE" not in skeleton.upper()
        assert ";" not in skeleton
        expected = (payload, payload.replace("*", "%"))
        assert any(e in literal for e in expected for literal in literals)
