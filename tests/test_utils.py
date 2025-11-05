"""Tests for utility functions."""

from aspy21.utils import chunked


class TestChunked:
    """Test the chunked utility function."""

    def test_chunked_basic(self) -> None:
        """Test basic chunking functionality."""
        items = [1, 2, 3, 4, 5, 6, 7, 8, 9]
        result = list(chunked(items, 3))
        expected = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
        assert result == expected

    def test_chunked_partial_last_chunk(self) -> None:
        """Test chunking when last chunk is partial."""
        items = [1, 2, 3, 4, 5, 6, 7]
        result = list(chunked(items, 3))
        expected = [[1, 2, 3], [4, 5, 6], [7]]
        assert result == expected

    def test_chunked_single_element(self) -> None:
        """Test chunking with single element."""
        items = [42]
        result = list(chunked(items, 3))
        expected = [[42]]
        assert result == expected

    def test_chunked_empty_iterable(self) -> None:
        """Test chunking empty iterable."""
        items: list[int] = []
        result = list(chunked(items, 3))
        expected: list[list[int]] = []
        assert result == expected

    def test_chunked_size_larger_than_iterable(self) -> None:
        """Test chunking when chunk size is larger than iterable."""
        items = [1, 2, 3]
        result = list(chunked(items, 10))
        expected = [[1, 2, 3]]
        assert result == expected

    def test_chunked_size_one(self) -> None:
        """Test chunking with size of 1."""
        items = [1, 2, 3]
        result = list(chunked(items, 1))
        expected = [[1], [2], [3]]
        assert result == expected

    def test_chunked_with_strings(self) -> None:
        """Test chunking with string items."""
        items = ["a", "b", "c", "d", "e"]
        result = list(chunked(items, 2))
        expected = [["a", "b"], ["c", "d"], ["e"]]
        assert result == expected

    def test_chunked_with_generator(self) -> None:
        """Test chunking with a generator input."""
        items = (x for x in range(5))
        result = list(chunked(items, 2))
        expected = [[0, 1], [2, 3], [4]]
        assert result == expected

    def test_chunked_invalid_size(self) -> None:
        """Test chunking with invalid size (zero or negative)."""
        items = [1, 2, 3]
        # size=0 should result in empty output as islice(it, 0) always returns empty
        result = list(chunked(items, 0))
        expected: list[list[int]] = []
        assert result == expected
