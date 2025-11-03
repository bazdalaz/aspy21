"""Tests for authentication functionality."""

from aspy21 import AspenClient


def test_basic_auth_with_tuple():
    """Test basic authentication using auth tuple."""
    with AspenClient(
        base_url="https://aspen.example.com/ProcessData",
        auth=("testuser", "testpass"),
    ) as client:
        assert client.auth == ("testuser", "testpass")


def test_no_authentication():
    """Test client creation without authentication."""
    with AspenClient(base_url="http://aspen.example.com/ProcessData") as client:
        assert client.auth is None
