"""Tests for the SSL context of clients created by AspenClient."""

from __future__ import annotations

import ssl

import httpx
import pytest

from aspy21 import AspenClient
from aspy21.client import _default_ssl_context

BASE_URL = "https://aspen.example.com/ProcessData"


@pytest.fixture
def verify_args(monkeypatch):
    """Record the verify argument of every httpx.Client created."""
    seen = []
    real_client = httpx.Client

    def client(*args, **kwargs):
        seen.append(kwargs["verify"])
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    return seen


def test_clients_share_one_checking_context(verify_args):
    for _ in range(3):
        AspenClient(BASE_URL, datasource="IP21").close()

    context = verify_args[0]
    assert isinstance(context, ssl.SSLContext)
    assert all(verify is context for verify in verify_args)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname


def test_context_built_once(monkeypatch):
    calls = []
    real_create = httpx.create_ssl_context

    def create(*args, **kwargs):
        calls.append(1)
        return real_create(*args, **kwargs)

    monkeypatch.setattr(httpx, "create_ssl_context", create)
    _default_ssl_context.cache_clear()
    try:
        for _ in range(3):
            AspenClient(BASE_URL, datasource="IP21").close()
    finally:
        _default_ssl_context.cache_clear()

    assert len(calls) == 1


def test_verify_ssl_false_turns_checks_off(verify_args):
    AspenClient(BASE_URL, datasource="IP21", verify_ssl=False).close()

    assert verify_args == [False]
