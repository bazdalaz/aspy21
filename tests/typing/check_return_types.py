"""Return types that type checkers infer for read() and search().

Checked by pyright (see [tool.pyright] include), not run by pytest: a wrong overload
fails `pyright` with an assert_type error.
"""

from __future__ import annotations

import pandas as pd
from typing_extensions import assert_type

from aspy21 import AspenClient, IncludeFields, OutputFormat, ReaderType


def check_read(client: AspenClient, output: OutputFormat) -> None:
    start, end = "2025-01-01 00:00:00", "2025-01-01 01:00:00"

    assert_type(client.read(["A"], start=start, end=end), list[dict])
    assert_type(client.read(["A"], start=start, end=end, output=OutputFormat.JSON), list[dict])
    assert_type(
        client.read(["A"], start=start, end=end, output=OutputFormat.DATAFRAME), pd.DataFrame
    )
    assert_type(
        client.read(
            ["A"],
            start="2025-01-01 00:00:00",
            end="2025-01-01 01:00:00",
            interval=600,
            read_type=ReaderType.AVG,
            include=IncludeFields.ALL,
            limit=10,
            output=OutputFormat.DATAFRAME,
        ),
        pd.DataFrame,
    )
    assert_type(client.read(["A"]), list[dict])  # snapshot
    # Output only known at runtime
    assert_type(
        client.read(["A"], start=start, end=end, output=output), "pd.DataFrame | list[dict]"
    )


def check_search(client: AspenClient, include: IncludeFields, start: str | None) -> None:
    # Search-only mode
    assert_type(client.search("T*"), list[str])
    assert_type(client.search("T*", include=IncludeFields.STATUS), list[str])
    assert_type(client.search("T*", include=IncludeFields.DESCRIPTION), list[dict])
    assert_type(client.search(description="pump", include=IncludeFields.ALL), list[dict])

    # Hybrid mode
    assert_type(client.search("T*", start="2025-01-01 00:00:00"), list[dict])
    assert_type(
        client.search("T*", start="2025-01-01 00:00:00", output=OutputFormat.DATAFRAME),
        pd.DataFrame,
    )

    # Mode or fields only known at runtime
    assert_type(client.search("T*", include=include), "pd.DataFrame | list[dict] | list[str]")
    assert_type(client.search("T*", start=start), "pd.DataFrame | list[dict] | list[str]")
