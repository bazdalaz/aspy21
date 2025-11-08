"""Tests for AspenClient error handling and edge cases."""

import httpx
import pytest

from aspy21 import AspenClient, ReaderType


class TestClientCloseBehavior:
    """Tests for client close() behavior."""

    def test_close_when_client_owns_http_client(self):
        """Test that close() closes the HTTP client when client owns it."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )
        # Client should own the HTTP client
        assert client._owns_client is True

        # Close should work
        client.close()

        # HTTP client should be closed
        assert client._client.is_closed

    def test_close_when_client_does_not_own_http_client(self):
        """Test that close() does not close injected HTTP client."""
        external_client = httpx.Client()

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
            http_client=external_client,
        )
        # Client should NOT own the HTTP client
        assert client._owns_client is False

        # Close should not close the external client
        client.close()

        # External client should still be open
        assert not external_client.is_closed

        # Clean up
        external_client.close()


class TestReadParameterValidation:
    """Tests for read() parameter validation and edge cases."""

    def test_auto_detect_end_time_when_missing(self, mock_api):
        """Test that end time is set to current time when start provided but end is None."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(200, json=[])
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        # Call read with start but no end
        result = client.read(
            tags=["TAG1"],
            start="2025-01-01 00:00:00",
            # end is None - should auto-detect
            interval=600,
            read_type=ReaderType.RAW,
        )

        # Should succeed and auto-set end time to current time
        assert result is not None
        client.close()

    def test_datasource_required_for_historical_reads(self):
        """Test that ValueError is raised when datasource missing for historical reads."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            # No datasource provided
        )

        with pytest.raises(ValueError, match="Datasource is required for historical reads"):
            client.read(
                tags=["TAG1"],
                start="2025-01-01 00:00:00",
                end="2025-01-01 01:00:00",
                interval=600,
                read_type=ReaderType.RAW,
            )

        client.close()

    def test_no_reader_available_for_read_type(self, mock_api, monkeypatch):
        """Test ValueError when no reader can handle the read type."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        # Mock all readers to return False for can_handle()
        for reader in client._readers:
            monkeypatch.setattr(reader, "can_handle", lambda *args, **kwargs: False)

        with pytest.raises(ValueError, match="No reader available for read_type"):
            client.read(
                tags=["TAG1"],
                start="2025-01-01 00:00:00",
                end="2025-01-01 01:00:00",
                interval=600,
                read_type=ReaderType.RAW,
            )

        client.close()


class TestSearchErrorHandling:
    """Tests for search() error handling."""

    def test_search_requires_datasource(self):
        """Test that ValueError is raised when datasource is missing for search."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            # No datasource
        )

        with pytest.raises(ValueError, match="Datasource is required for search"):
            client.search(tag="TEMP*")

        client.close()

    def test_browse_endpoint_api_error_response(self, mock_api):
        """Test handling of API error from Browse endpoint."""
        mock_api.get("https://aspen.local/ProcessData/AtProcessDataREST.dll/Browse").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "result": {
                            "er": 1,
                            "ec": 403,
                            "es": "Access denied to datasource",
                        }
                    }
                },
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        with pytest.raises(ValueError, match="Access denied to datasource"):
            client.search(tag="TEMP*")

        client.close()

    def test_browse_response_no_tags_key(self, mock_api):
        """Test handling when Browse response has no 'tags' key."""
        mock_api.get("https://aspen.local/ProcessData/AtProcessDataREST.dll/Browse").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "result": {
                            "er": 0,
                            "ec": 0,
                            "es": "",
                        }
                    }
                },
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        # Should return empty list when no tags found
        result = client.search(tag="NONEXISTENT*")
        assert result == []

        client.close()

    def test_search_network_exception(self, mock_api):
        """Test exception handling when Browse endpoint fails."""
        mock_api.get("https://aspen.local/ProcessData/AtProcessDataREST.dll/Browse").mock(
            side_effect=httpx.TimeoutException("Connection timeout")
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        with pytest.raises(httpx.TimeoutException):
            client.search(tag="TEMP*")

        client.close()


class TestSearchWithDescription:
    """Tests for search() with description parameter (SQL endpoint path)."""

    def test_search_with_description_requires_datasource(self):
        """Test that ValueError is raised when datasource is missing."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            # No datasource
        )

        with pytest.raises(ValueError, match="Datasource is required"):
            client.search(tag="TEMP*", description="temperature")

        client.close()

    def test_search_with_description_api_error(self, mock_api):
        """Test handling of API error from SQL search."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "result": {
                                "er": 1,
                                "es": "Invalid datasource name",
                            }
                        }
                    ]
                },
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="INVALID",
        )

        with pytest.raises(ValueError, match="Invalid datasource name"):
            client.search(tag="TEMP*", description="temperature")

        client.close()

    def test_search_with_description_network_error(self, mock_api):
        """Test exception handling when SQL search fails."""
        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        with pytest.raises(httpx.ConnectError):
            client.search(tag="TEMP*", description="temperature")

        client.close()


class TestHybridSearchMode:
    """Tests for search() in hybrid mode (with start parameter)."""

    def test_hybrid_mode_calls_both_search_and_read(self, mock_api):
        """Test that hybrid mode (with start time) calls both search and read."""
        mock_api.get("https://aspen.local/ProcessData/AtProcessDataREST.dll/Browse").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "tags": [
                            {"t": "TEMP_101", "n": "Temperature 101", "m": "real"},
                        ]
                    }
                },
            )
        )

        mock_api.post("https://aspen.local/ProcessData/AtProcessDataREST.dll/SQL").mock(
            return_value=httpx.Response(
                200,
                json=[{"ts": "2025-01-01T00:00:00Z", "name": "TEMP_101", "value": 25.5}],
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData/AtProcessDataREST.dll",
            datasource="IP21",
        )

        # Search with start time (hybrid mode)
        result = client.search(
            tag="TEMP*",
            start="2025-01-01 00:00:00",
            end="2025-01-01 01:00:00",
            interval=600,
        )

        # Should return data (DataFrame or list)
        assert result is not None

        client.close()
