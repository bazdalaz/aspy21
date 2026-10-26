"""Tests for the option enums."""

from __future__ import annotations

import pytest

from aspy21 import IncludeFields, OutputFormat, ReaderType


@pytest.mark.parametrize(
    "member", [*ReaderType, *IncludeFields, *OutputFormat], ids=lambda member: repr(member)
)
def test_enum_members_are_their_values_as_strings(member):
    """Options compare equal to, print as and format as their string value."""
    assert member == member.value
    assert str(member) == member.value
    assert f"{member}" == member.value
