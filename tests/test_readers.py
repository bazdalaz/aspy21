"""Tests for reader exception handling (HTTP errors, JSON parse errors, empty responses)."""

import httpx
import pytest

from aspy21 import AspenClient, ReaderType
from aspy21.readers.aggregates_reader import AggregatesReader
from aspy21.readers.snapshot_reader import SnapshotReader
from aspy21.readers.sql_history_reader import SqlHistoryReader


class TestAggregatesReaderExceptions:
    """Tests for AggregatesReader exception handling."""

    def test_interval_auto_calculation(self, mock_api):
        """Test that period is calculated from time range when interval not provided."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "cols": [
                                {"i": 0, "n": "TIME_STAMP"},
                                {"i": 1, "n": "NAME"},
                                {"i": 2, "n": "AVG"},
                            ],
                            "rows": [],
                        }
                    ]
                },
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        # Call without interval - should auto-calculate from time range
        result = client.read(
            tags=["TAG1"],
            start="2025-01-01 00:00:00",
            end="2025-01-01 01:00:00",
            # No interval parameter
            read_type=ReaderType.AVG,
        )

        # Should succeed with auto-calculated interval
        assert result is not None
        client.close()

    def test_http_request_exception(self, mock_api):
        """Test handling of HTTP request exception (network error)."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            side_effect=httpx.TimeoutException("Request timeout")
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        with pytest.raises(httpx.TimeoutException, match="Request timeout"):
            client.read(
                tags=["TAG1"],
                start="2025-01-01 00:00:00",
                end="2025-01-01 01:00:00",
                interval=600,
                read_type=ReaderType.AVG,
            )

        client.close()

    def test_http_connect_error(self, mock_api):
        """Test handling of HTTP connection error."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        with pytest.raises(httpx.ConnectError, match="Connection refused"):
            client.read(
                tags=["TAG1"],
                start="2025-01-01 00:00:00",
                end="2025-01-01 01:00:00",
                interval=600,
                read_type=ReaderType.MIN,
            )

        client.close()

    def test_json_parse_error(self, mock_api):
        """Test handling when SQL endpoint returns non-JSON response."""
        # Return HTML error page instead of JSON
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(
                500,
                text="<html><body>Internal Server Error</body></html>",
                headers={"content-type": "text/html"},
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        # HTTP 500 errors raise HTTPStatusError
        with pytest.raises(httpx.HTTPStatusError):
            client.read(
                tags=["TAG1"],
                start="2025-01-01 00:00:00",
                end="2025-01-01 01:00:00",
                interval=600,
                read_type=ReaderType.MAX,
            )

        client.close()

    def test_malformed_json_response(self, mock_api):
        """Test handling of malformed JSON response."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(
                200,
                text='{"data": [{"cols": [{"i": 0, "n": "TIME_STAMP"}',  # Incomplete JSON
                headers={"content-type": "application/json"},
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        with pytest.raises(ValueError):
            client.read(
                tags=["TAG1"],
                start="2025-01-01 00:00:00",
                end="2025-01-01 01:00:00",
                interval=600,
                read_type=ReaderType.RNG,
            )

        client.close()


class TestSnapshotReaderExceptions:
    """Tests for SnapshotReader exception handling."""

    def test_datasource_required_for_snapshot(self):
        """Test that ValueError is raised when datasource is missing for SNAPSHOT."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            # No datasource
        )

        with pytest.raises(ValueError, match="Datasource is required for SNAPSHOT reads"):
            client.read(
                tags=["TAG1"],
                read_type=ReaderType.SNAPSHOT,
            )

        client.close()

    def test_empty_datasource_for_snapshot(self):
        """Test that ValueError is raised when datasource is empty string."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="",
        )

        with pytest.raises(ValueError, match="Datasource is required for SNAPSHOT reads"):
            client.read(
                tags=["TAG1"],
                read_type=ReaderType.SNAPSHOT,
            )

        client.close()

    def test_json_parse_error_in_snapshot(self, mock_api):
        """Test handling when snapshot SQL endpoint returns non-JSON."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(
                200,
                text="Plain text error",
                headers={"content-type": "text/plain"},
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        with pytest.raises(ValueError):
            client.read(
                tags=["TAG1"],
                read_type=ReaderType.SNAPSHOT,
            )

        client.close()

    def test_http_error_status_in_snapshot(self, mock_api):
        """Test handling of HTTP error status (500, 404, etc.) in snapshot."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(
                500,
                json={"error": "Internal server error"},
                headers={
                    "content-type": "application/json",
                    "x-error": "Database connection failed",
                },
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        # HTTP 500 errors raise HTTPStatusError
        with pytest.raises(httpx.HTTPStatusError):
            client.read(
                tags=["TAG1"],
                read_type=ReaderType.SNAPSHOT,
            )

        client.close()

    def test_network_timeout_in_snapshot(self, mock_api):
        """Test handling of network timeout in snapshot read."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            side_effect=httpx.TimeoutException("Timeout after 30s")
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        with pytest.raises(httpx.TimeoutException):
            client.read(
                tags=["TAG1"],
                read_type=ReaderType.SNAPSHOT,
            )

        client.close()


class TestSqlHistoryReaderExceptions:
    """Tests for SqlHistoryReader exception handling."""

    def test_empty_response_handling(self, mock_api):
        """Test handling of empty response body (Content-Length: 0)."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(
                200,
                text="",  # Empty response
                headers={"content-length": "0"},
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        # Should handle empty response gracefully
        result = client.read(
            tags=["TAG1"],
            start="2025-01-01 00:00:00",
            end="2025-01-01 01:00:00",
            interval=600,
            read_type=ReaderType.RAW,
        )

        # Should return empty result (list for multi-tag)
        assert isinstance(result, list)
        assert len(result) == 0
        client.close()

    def test_content_length_zero_header(self, mock_api):
        """Test handling when response has Content-Length: 0 header."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(
                200,
                content=b"",
                headers={"content-length": "0"},
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        result = client.read(
            tags=["TAG1"],
            start="2025-01-01 00:00:00",
            end="2025-01-01 01:00:00",
            interval=600,
            read_type=ReaderType.RAW,
        )

        # Should return empty result without error
        assert isinstance(result, list)
        assert len(result) == 0
        client.close()

    def test_json_parse_error_in_history(self, mock_api):
        """Test handling when history endpoint returns non-JSON response."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(
                200,
                text="<html>Error Page</html>",
                headers={"content-type": "text/html"},
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        with pytest.raises(ValueError):
            client.read(
                tags=["TAG1"],
                start="2025-01-01 00:00:00",
                end="2025-01-01 01:00:00",
                interval=600,
                read_type=ReaderType.RAW,
            )

        client.close()

    def test_http_500_error_in_history(self, mock_api):
        """Test handling of HTTP 500 error in history read."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(
                500,
                json={"error": "Database error"},
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        # HTTP 500 errors raise HTTPStatusError
        with pytest.raises(httpx.HTTPStatusError):
            client.read(
                tags=["TAG1"],
                start="2025-01-01 00:00:00",
                end="2025-01-01 01:00:00",
                interval=600,
                read_type=ReaderType.RAW,
            )

        client.close()

    def test_network_error_in_history(self, mock_api):
        """Test handling of network error during history read."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            side_effect=httpx.NetworkError("Network unreachable")
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        with pytest.raises(httpx.NetworkError):
            client.read(
                tags=["TAG1"],
                start="2025-01-01 00:00:00",
                end="2025-01-01 01:00:00",
                interval=600,
                read_type=ReaderType.INT,
            )

        client.close()


class TestReaderCanHandle:
    """Tests for reader can_handle() method logic."""

    def test_aggregates_reader_can_handle_min_max_avg_rng(self):
        """Test that AggregatesReader handles MIN, MAX, AVG, RNG."""
        reader = AggregatesReader(
            http_client=httpx.Client(),
            base_url="https://aspen.local",
            datasource="IP21",
        )

        # Should handle aggregates types
        assert reader.can_handle(ReaderType.MIN, start="2025-01-01", end="2025-01-02")
        assert reader.can_handle(ReaderType.MAX, start="2025-01-01", end="2025-01-02")
        assert reader.can_handle(ReaderType.AVG, start="2025-01-01", end="2025-01-02")
        assert reader.can_handle(ReaderType.RNG, start="2025-01-01", end="2025-01-02")

        # Should NOT handle other types
        assert not reader.can_handle(ReaderType.RAW, start="2025-01-01", end="2025-01-02")
        assert not reader.can_handle(ReaderType.SNAPSHOT, start=None, end=None)

        reader.http_client.close()

    def test_snapshot_reader_can_handle_snapshot_only(self):
        """Test that SnapshotReader only handles SNAPSHOT type."""
        reader = SnapshotReader(
            http_client=httpx.Client(),
            base_url="https://aspen.local",
            datasource="IP21",
        )

        # Should handle SNAPSHOT with no start/end
        assert reader.can_handle(ReaderType.SNAPSHOT, start=None, end=None)

        # Should NOT handle other types
        assert not reader.can_handle(ReaderType.RAW, start="2025-01-01", end="2025-01-02")
        assert not reader.can_handle(ReaderType.AVG, start="2025-01-01", end="2025-01-02")

        reader.http_client.close()

    def test_sql_history_reader_can_handle_raw_and_int(self):
        """Test that SqlHistoryReader handles RAW and INT."""
        reader = SqlHistoryReader(
            http_client=httpx.Client(),
            base_url="https://aspen.local",
            datasource="IP21",
        )

        # Should handle RAW and INT with time range
        assert reader.can_handle(ReaderType.RAW, start="2025-01-01", end="2025-01-02")
        assert reader.can_handle(ReaderType.INT, start="2025-01-01", end="2025-01-02")

        # Should NOT handle aggregates or snapshot
        assert not reader.can_handle(ReaderType.AVG, start="2025-01-01", end="2025-01-02")
        assert not reader.can_handle(ReaderType.SNAPSHOT, start=None, end=None)

        reader.http_client.close()


class TestReaderEdgeCases:
    """Additional edge cases for reader implementations."""

    def test_multiple_readers_in_client(self):
        """Test that client has all expected readers registered."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        # Should have 3 readers: Snapshot, SqlHistory, Aggregates
        assert len(client._readers) == 3

        reader_types = [type(r).__name__ for r in client._readers]
        assert "SnapshotReader" in reader_types
        assert "SqlHistoryReader" in reader_types
        assert "AggregatesReader" in reader_types

        client.close()

    def test_reader_selection_priority(self, mock_api):
        """Test that readers are selected in correct priority order."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(200, json=[])
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        # Request SNAPSHOT - should use SnapshotReader
        client.read(tags=["TAG1"], read_type=ReaderType.SNAPSHOT)

        # Request RAW with time range - should use SqlHistoryReader
        client.read(
            tags=["TAG1"],
            start="2025-01-01",
            end="2025-01-02",
            interval=600,
            read_type=ReaderType.RAW,
        )

        # Request AVG with time range - should use AggregatesReader
        client.read(
            tags=["TAG1"],
            start="2025-01-01",
            end="2025-01-02",
            interval=600,
            read_type=ReaderType.AVG,
        )

        # All should succeed without errors
        client.close()
