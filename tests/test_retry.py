"""Tests for retrying transient HTTP failures."""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

from aspy21 import AspenClient, AspenSqlError, IncludeFields, ReaderType
from aspy21.readers import AggregatesReader, SnapshotReader, SqlHistoryReader
from aspy21.retry import RETRY_AFTER_MAX, send

BASE_URL = "https://aspen.local/ProcessData/AtProcessDataREST.dll"
SQL_URL = f"{BASE_URL}/SQL"
BROWSE_URL = f"{BASE_URL}/Browse"
URL = "https://aspen.local/endpoint"

OK_HISTORY = [{"ts": "2025-01-01T00:00:00Z", "name": "TAG1", "value": 1.0}]
OK_SNAPSHOT = [{"name": "TAG1", "name->ip_input_value": 1.0}]
OK_AGGREGATES = [{"ts": "2025-01-01T01:00:00Z", "name": "TAG1", "avg": 1.0}]
OK_BROWSE = {"data": {"tags": [{"t": "TAG1", "n": "Tag one"}]}}
OK_SQL_SEARCH = {"data": [{"rows": [{"fld": [{"i": 0, "v": "TAG1"}, {"i": 1, "v": "Tag one"}]}]}]}
SQL_ERROR = [{"AtPD_ErrorCode": -1, "AtPD_ErrorString": "Syntax error"}]


def _send(retries: int = 2, method: str = "GET", **kwargs) -> httpx.Response:
    with httpx.Client() as client:
        return send(client, method, URL, retries=retries, **kwargs)


class TestWhatIsRetried:
    @pytest.mark.parametrize("status", [429, 502, 503, 504])
    @respx.mock
    def test_transient_status_retried(self, status):
        route = respx.get(URL).mock(side_effect=[httpx.Response(status), httpx.Response(200)])

        assert _send().status_code == 200
        assert route.call_count == 2

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 501])
    @respx.mock
    def test_other_error_status_not_retried(self, status):
        route = respx.get(URL).mock(return_value=httpx.Response(status))

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            _send()

        assert exc_info.value.response.status_code == status
        assert route.call_count == 1

    @pytest.mark.parametrize(
        "error",
        [
            httpx.ConnectError("refused"),
            httpx.ConnectTimeout("connect timeout"),
            httpx.ReadError("connection reset"),
            httpx.WriteError("broken pipe"),
            httpx.RemoteProtocolError("server disconnected"),
        ],
        ids=lambda e: type(e).__name__,
    )
    @respx.mock
    def test_transient_network_error_retried(self, error):
        route = respx.get(URL).mock(side_effect=[error, httpx.Response(200)])

        assert _send().status_code == 200
        assert route.call_count == 2

    @pytest.mark.parametrize(
        "error",
        [
            httpx.ReadTimeout("read timeout"),
            httpx.PoolTimeout("pool timeout"),
            httpx.UnsupportedProtocol("ftp"),
            httpx.TooManyRedirects("loop"),
        ],
        ids=lambda e: type(e).__name__,
    )
    @respx.mock
    def test_other_request_error_not_retried(self, error):
        route = respx.get(URL).mock(side_effect=error)

        with pytest.raises(type(error)):
            _send()

        assert route.call_count == 1

    @respx.mock
    def test_success_is_returned_without_retry(self, retry_sleeps):
        route = respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": True}))

        assert _send().json() == {"ok": True}
        assert route.call_count == 1
        assert retry_sleeps == []


class TestAttempts:
    @respx.mock
    def test_gives_up_after_retries_and_raises_last_status_error(self):
        route = respx.get(URL).mock(return_value=httpx.Response(503))

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            _send(retries=2)

        assert exc_info.value.response.status_code == 503
        assert route.call_count == 3

    @respx.mock
    def test_gives_up_after_retries_and_raises_original_network_error(self):
        route = respx.get(URL).mock(side_effect=httpx.ConnectError("refused"))

        with pytest.raises(httpx.ConnectError, match="refused"):
            _send(retries=2)

        assert route.call_count == 3

    @respx.mock
    def test_zero_retries_sends_once(self, retry_sleeps):
        route = respx.get(URL).mock(return_value=httpx.Response(503))

        with pytest.raises(httpx.HTTPStatusError):
            _send(retries=0)

        assert route.call_count == 1
        assert retry_sleeps == []

    @respx.mock
    def test_recovers_on_last_attempt(self):
        route = respx.get(URL).mock(
            side_effect=[httpx.Response(503), httpx.ConnectError("x"), httpx.Response(200)]
        )

        assert _send(retries=2).status_code == 200
        assert route.call_count == 3

    @respx.mock
    def test_non_transient_error_after_transient_stops(self):
        route = respx.get(URL).mock(side_effect=[httpx.Response(503), httpx.Response(404)])

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            _send(retries=5)

        assert exc_info.value.response.status_code == 404
        assert route.call_count == 2

    @respx.mock
    def test_request_is_resent_unchanged(self):
        route = respx.post(URL).mock(side_effect=[httpx.Response(503), httpx.Response(200)])

        _send(method="POST", content="<SQL/>", headers={"Content-Type": "text/xml"})

        for call in route.calls:
            assert call.request.content == b"<SQL/>"
            assert call.request.headers["Content-Type"] == "text/xml"


class TestWaits:
    @respx.mock
    def test_exponential_backoff(self, retry_sleeps):
        respx.get(URL).mock(return_value=httpx.Response(503))

        with pytest.raises(httpx.HTTPStatusError):
            _send(retries=6)

        assert retry_sleeps == [0.5, 1.0, 2.0, 4.0, 8.0, 8.0]

    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            ("3", 3.0),
            ("0", 0.0),
            ("1.5", 1.5),
            ("120", RETRY_AFTER_MAX),
            ("-5", 0.0),
            ("Wed, 21 Oct 2026 07:28:00 GMT", 0.5),
            ("soon", 0.5),
        ],
    )
    @respx.mock
    def test_retry_after_header(self, retry_sleeps, header, expected):
        respx.get(URL).mock(
            side_effect=[httpx.Response(429, headers={"Retry-After": header}), httpx.Response(200)]
        )

        _send()

        assert retry_sleeps == [expected]

    @respx.mock
    def test_retry_after_used_only_for_its_response(self, retry_sleeps):
        respx.get(URL).mock(
            side_effect=[
                httpx.Response(503, headers={"Retry-After": "5"}),
                httpx.Response(503),
                httpx.Response(200),
            ]
        )

        _send()

        assert retry_sleeps == [5.0, 1.0]


class TestLogging:
    @respx.mock
    def test_each_retry_logged_as_warning(self, caplog):
        respx.get(URL).mock(
            side_effect=[httpx.Response(503), httpx.ConnectError("x"), httpx.Response(200)]
        )

        with caplog.at_level(logging.WARNING, logger="aspy21.retry"):
            _send()

        messages = [r.getMessage() for r in caplog.records]
        assert messages == [
            "Request failed (HTTP 503), retry 1 in 0.5s",
            "Request failed (ConnectError), retry 2 in 1.0s",
        ]

    @respx.mock
    def test_no_warning_without_retry(self, caplog):
        respx.get(URL).mock(return_value=httpx.Response(200))

        with caplog.at_level(logging.WARNING, logger="aspy21.retry"):
            _send()

        assert caplog.records == []


def _client(**kwargs) -> AspenClient:
    kwargs.setdefault("datasource", "IP21")
    return AspenClient(BASE_URL, **kwargs)


def _read_history(client):
    return client.read(["TAG1"], start="2025-01-01 00:00:00", end="2025-01-01 01:00:00")


def _read_snapshot(client):
    return client.read(["TAG1"])


def _read_aggregates(client):
    return client.read(
        ["TAG1"],
        start="2025-01-01 00:00:00",
        end="2025-01-01 01:00:00",
        read_type=ReaderType.AVG,
        interval=3600,
    )


def _search_browse(client):
    return client.search(tag="TAG*")


def _search_description(client):
    return client.search(description="Tag", include=IncludeFields.DESCRIPTION)


OPERATIONS = [
    pytest.param(_read_history, "POST", SQL_URL, OK_HISTORY, id="read_history"),
    pytest.param(_read_snapshot, "POST", SQL_URL, OK_SNAPSHOT, id="read_snapshot"),
    pytest.param(_read_aggregates, "POST", SQL_URL, OK_AGGREGATES, id="read_aggregates"),
    pytest.param(_search_browse, "GET", BROWSE_URL, OK_BROWSE, id="search_browse"),
    pytest.param(_search_description, "POST", SQL_URL, OK_SQL_SEARCH, id="search_description"),
]


class TestClientRetries:
    @pytest.mark.parametrize(("operation", "method", "url", "ok_body"), OPERATIONS)
    @respx.mock
    def test_every_request_is_retried(self, operation, method, url, ok_body):
        route = respx.route(method=method, url__startswith=url).mock(
            side_effect=[
                httpx.Response(503),
                httpx.ConnectError("refused"),
                httpx.Response(200, json=ok_body),
            ]
        )

        with _client() as client:
            result = operation(client)

        assert len(result) > 0
        assert route.call_count == 3

    @pytest.mark.parametrize(("operation", "method", "url", "ok_body"), OPERATIONS)
    @respx.mock
    def test_retries_zero_disables_retry(self, operation, method, url, ok_body):
        route = respx.route(method=method, url__startswith=url).mock(
            return_value=httpx.Response(503)
        )

        with _client(retries=0) as client, pytest.raises(httpx.HTTPStatusError):
            operation(client)

        assert route.call_count == 1

    @respx.mock
    def test_default_is_two_retries(self):
        route = respx.post(SQL_URL).mock(return_value=httpx.Response(503))

        with _client() as client:
            assert client.retries == 2
            with pytest.raises(httpx.HTTPStatusError):
                _read_history(client)

        assert route.call_count == 3

    @respx.mock
    def test_custom_retry_count(self):
        route = respx.post(SQL_URL).mock(return_value=httpx.Response(503))

        with _client(retries=4) as client, pytest.raises(httpx.HTTPStatusError):
            _read_history(client)

        assert route.call_count == 5

    @respx.mock
    def test_sql_error_not_retried(self):
        route = respx.post(SQL_URL).mock(return_value=httpx.Response(200, json=SQL_ERROR))

        with _client() as client, pytest.raises(AspenSqlError):
            _read_history(client)

        assert route.call_count == 1

    @respx.mock
    def test_read_timeout_not_retried(self):
        route = respx.post(SQL_URL).mock(side_effect=httpx.ReadTimeout("slow query"))

        with _client() as client, pytest.raises(httpx.ReadTimeout):
            _read_history(client)

        assert route.call_count == 1

    @respx.mock
    def test_injected_http_client_is_retried(self):
        route = respx.post(SQL_URL).mock(
            side_effect=[httpx.Response(502), httpx.Response(200, json=OK_HISTORY)]
        )

        with httpx.Client() as http_client, _client(http_client=http_client) as client:
            assert len(_read_history(client)) == 1

        assert route.call_count == 2

    @respx.mock
    def test_retried_result_is_cached_once(self):
        route = respx.post(SQL_URL).mock(
            side_effect=[httpx.Response(503), httpx.Response(200, json=OK_HISTORY)]
        )

        with _client(cache=True) as client:
            first = _read_history(client)
            second = _read_history(client)

        assert first == second
        assert route.call_count == 2

    @pytest.mark.parametrize("value", [-1, 1.5, "2", None, True])
    def test_invalid_retries_rejected(self, value):
        with pytest.raises(ValueError, match="retries must be a non-negative integer"):
            AspenClient(BASE_URL, retries=value)


class TestReaderDefaults:
    @pytest.mark.parametrize("reader_cls", [SnapshotReader, SqlHistoryReader, AggregatesReader])
    def test_readers_do_not_retry_by_default(self, reader_cls):
        with httpx.Client() as http_client:
            assert reader_cls(BASE_URL, "IP21", http_client).retries == 0

    @pytest.mark.parametrize("reader_cls", [SnapshotReader, SqlHistoryReader, AggregatesReader])
    def test_client_passes_retries_to_readers(self, reader_cls):
        with _client(retries=5) as client:
            reader = next(r for r in client._readers if type(r) is reader_cls)
            assert reader.retries == 5
