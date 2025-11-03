"""Utility functions for the Aspen client."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import islice
from typing import TypeVar

T = TypeVar("T")


def chunked(iterable: Iterable[T], size: int) -> Iterable[list[T]]:
    """Split an iterable into chunks of specified size.

    Args:
        iterable: The input iterable to be chunked
        size: Maximum size of each chunk

    Yields:
        Lists of items, each containing up to 'size' elements
    """
    it = iter(iterable)
    while True:
        batch = list(islice(it, size))
        if not batch:
            return
        yield batch
