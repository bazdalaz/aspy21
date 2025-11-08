"""Performance benchmarks for output formats and data transformations.

Benchmarks different output formats and data processing operations.

Run with: pytest tests/benchmark_formats.py --benchmark-only
"""

import httpx
import pytest

from aspy21 import AspenClient, IncludeFields, OutputFormat, ReaderType


@pytest.fixture
def mock_api_large_dataset(respx_mock):
    """Mock API returning a larger dataset for format comparison."""
    # Generate 1000 data points
    data = []
    for i in range(1000):
        data.append(
            {
                "ts": f"2025-01-01T{i // 60:02d}:{i % 60:02d}:00.000Z",
                "name": "TAG1",
                "value": 25.0 + (i * 0.01),
            }
        )

    respx_mock.post("https://aspen.local/ProcessData/SQL").mock(
        return_value=httpx.Response(200, json=data)
    )
    return respx_mock


@pytest.fixture
def mock_api_multi_tag(respx_mock):
    """Mock API returning multiple tags."""
    data = []
    for tag_num in range(1, 11):  # 10 tags
        for i in range(100):  # 100 points each
            data.append(
                {
                    "ts": f"2025-01-01T08:{i % 60:02d}:00.000Z",
                    "name": f"TAG{tag_num}",
                    "value": 20.0 + tag_num + (i * 0.1),
                }
            )

    respx_mock.post("https://aspen.local/ProcessData/SQL").mock(
        return_value=httpx.Response(200, json=data)
    )
    return respx_mock


class TestOutputFormatPerformance:
    """Benchmark different output format performance."""

    def test_benchmark_json_output(self, benchmark, mock_api_large_dataset):
        """Benchmark: JSON output format (baseline)."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData",
            datasource="IP21",
            cache=False,
        )

        result = benchmark(
            client.read,
            tags=["TAG1"],
            start="2025-01-01 08:00:00",
            end="2025-01-01 09:00:00",
            read_type=ReaderType.RAW,
            output=OutputFormat.JSON,
        )

        assert isinstance(result, list)
        assert len(result) == 1000
        client.close()

    def test_benchmark_dataframe_output(self, benchmark, mock_api_large_dataset):
        """Benchmark: DataFrame output format (conversion overhead)."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData",
            datasource="IP21",
            cache=False,
        )

        result = benchmark(
            client.read,
            tags=["TAG1"],
            start="2025-01-01 08:00:00",
            end="2025-01-01 09:00:00",
            read_type=ReaderType.RAW,
            output=OutputFormat.DATAFRAME,
        )

        assert len(result) == 1000
        client.close()

    def test_benchmark_dataframe_with_status(self, benchmark, mock_api_large_dataset):
        """Benchmark: DataFrame with status column."""
        # Update mock to include status
        mock_api_large_dataset.post("https://aspen.local/ProcessData/SQL").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "ts": f"2025-01-01T08:{i % 60:02d}:00.000Z",
                        "name": "TAG1",
                        "value": 25.0 + (i * 0.01),
                        "status": 8,
                    }
                    for i in range(1000)
                ],
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData",
            datasource="IP21",
            cache=False,
        )

        result = benchmark(
            client.read,
            tags=["TAG1"],
            start="2025-01-01 08:00:00",
            end="2025-01-01 09:00:00",
            read_type=ReaderType.RAW,
            include=IncludeFields.STATUS,
            output=OutputFormat.DATAFRAME,
        )

        assert "TAG1_status" in result.columns
        client.close()

    def test_benchmark_multi_tag_dataframe(self, benchmark, mock_api_multi_tag):
        """Benchmark: Multiple tags with DataFrame output."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData",
            datasource="IP21",
            cache=False,
        )

        result = benchmark(
            client.read,
            tags=[f"TAG{i}" for i in range(1, 11)],
            start="2025-01-01 08:00:00",
            end="2025-01-01 09:00:00",
            read_type=ReaderType.RAW,
            output=OutputFormat.DATAFRAME,
        )

        assert len(result.columns) == 10
        client.close()


class TestReaderTypePerformance:
    """Benchmark different reader types."""

    def test_benchmark_raw_reader(self, benchmark, mock_api_large_dataset):
        """Benchmark: RAW reader type."""
        client = AspenClient(
            base_url="https://aspen.local/ProcessData",
            datasource="IP21",
            cache=False,
        )

        result = benchmark(
            client.read,
            tags=["TAG1"],
            start="2025-01-01 08:00:00",
            end="2025-01-01 09:00:00",
            read_type=ReaderType.RAW,
            output=OutputFormat.JSON,
        )

        assert len(result) > 0
        client.close()

    def test_benchmark_snapshot_reader(self, benchmark, respx_mock):
        """Benchmark: SNAPSHOT reader type."""
        respx_mock.post("https://aspen.local/ProcessData/SQL").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "name": "TAG1",
                        "name->ip_description": "Test Tag",
                        "name->ip_input_value": 25.5,
                    }
                ],
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData",
            datasource="IP21",
            cache=False,
        )

        result = benchmark(client.read, tags=["TAG1"], read_type=ReaderType.SNAPSHOT)

        assert len(result) > 0
        client.close()

    def test_benchmark_aggregates_reader(self, benchmark, respx_mock):
        """Benchmark: Aggregates (AVG) reader type."""
        # Mock aggregates response
        respx_mock.post("https://aspen.local/ProcessData/SQL").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"ts": "2025-01-01T08:00:00Z", "name": "TAG1", "avg": 25.5},
                ],
            )
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData",
            datasource="IP21",
            cache=False,
        )

        result = benchmark(
            client.read,
            tags=["TAG1"],
            start="2025-01-01 08:00:00",
            end="2025-01-01 09:00:00",
            interval=600,
            read_type=ReaderType.AVG,
        )

        assert len(result) > 0
        client.close()


class TestDataVolumeScaling:
    """Benchmark performance with varying data volumes."""

    @pytest.mark.parametrize("num_points", [100, 500, 1000, 5000])
    def test_benchmark_varying_data_sizes(self, benchmark, respx_mock, num_points):
        """Benchmark: Performance with different data volumes."""
        data = [
            {
                "ts": f"2025-01-01T{i // 3600:02d}:{(i % 3600) // 60:02d}:00.000Z",
                "name": "TAG1",
                "value": 25.0 + (i * 0.001),
            }
            for i in range(num_points)
        ]

        respx_mock.post("https://aspen.local/ProcessData/SQL").mock(
            return_value=httpx.Response(200, json=data)
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData",
            datasource="IP21",
            cache=False,
        )

        result = benchmark(
            client.read,
            tags=["TAG1"],
            start="2025-01-01 00:00:00",
            end="2025-01-01 23:59:59",
            read_type=ReaderType.RAW,
            output=OutputFormat.DATAFRAME,
        )

        assert len(result) == num_points
        client.close()

    @pytest.mark.parametrize("num_tags", [1, 5, 10, 20])
    def test_benchmark_varying_tag_counts(self, benchmark, respx_mock, num_tags):
        """Benchmark: Performance with different numbers of tags."""
        data = []
        for tag_num in range(1, num_tags + 1):
            for i in range(100):
                data.append(
                    {
                        "ts": f"2025-01-01T08:{i % 60:02d}:00.000Z",
                        "name": f"TAG{tag_num}",
                        "value": 20.0 + tag_num + (i * 0.1),
                    }
                )

        respx_mock.post("https://aspen.local/ProcessData/SQL").mock(
            return_value=httpx.Response(200, json=data)
        )

        client = AspenClient(
            base_url="https://aspen.local/ProcessData",
            datasource="IP21",
            cache=False,
        )

        result = benchmark(
            client.read,
            tags=[f"TAG{i}" for i in range(1, num_tags + 1)],
            start="2025-01-01 08:00:00",
            end="2025-01-01 09:00:00",
            read_type=ReaderType.RAW,
            output=OutputFormat.DATAFRAME,
        )

        assert len(result.columns) == num_tags
        client.close()


if __name__ == "__main__":
    pytest.main([__file__, "--benchmark-only", "-v"])
