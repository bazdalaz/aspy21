import pytest
import respx


@pytest.fixture
def mock_api():
    with respx.mock(base_url="https://aspen.local/ProcessData") as respx_mock:
        yield respx_mock
