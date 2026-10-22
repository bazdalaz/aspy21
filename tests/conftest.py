import pytest
import respx


@pytest.fixture
def mock_api():
    with respx.mock(base_url="https://aspen.local/ProcessData") as respx_mock:
        yield respx_mock


@pytest.fixture(autouse=True)
def retry_sleeps(monkeypatch):
    """Skip waits between request retries; yields the waits that would have happened."""
    sleeps: list[float] = []
    monkeypatch.setattr("aspy21.retry._sleep", sleeps.append)
    yield sleeps
