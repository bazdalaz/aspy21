"""Smoke test for the SQL/XML escaping fix against a real IP.21 server.

Usage:
    ASPEN_BASE_URL=... ASPEN_USER=... ASPEN_PASS=... ASPEN_DATASOURCE=IP21 \
    ASPEN_TAG=<a real tag> python scripts/smoke_test.py
"""

import os
from datetime import datetime, timedelta

import aspy21
from aspy21 import AspenClient, ReaderType

print(f"aspy21 {aspy21.__version__} from {aspy21.__file__}")

tag = os.environ["ASPEN_TAG"]
end = datetime.now() - timedelta(hours=1)
start = end - timedelta(hours=1)

with AspenClient(
    base_url=os.environ["ASPEN_BASE_URL"],
    auth=(os.environ["ASPEN_USER"], os.environ["ASPEN_PASS"]),
    datasource=os.environ["ASPEN_DATASOURCE"],
) as c:
    checks = {
        "browse search": lambda: c.search(tag=tag[:3] + "*", limit=5),
        "description search": lambda: c.search(description="temp", limit=5),
        "quote in description (escaping)": lambda: c.search(description="O'Brien", limit=5),
        "quote in tag pattern (escaping)": lambda: c.search(
            tag="X'*", description="temp", limit=5
        ),
        "history read (INT)": lambda: c.read(
            [tag], start=start.isoformat(), end=end.isoformat(), interval=600
        )[:3],
        "snapshot read": lambda: c.read([tag]),
        "aggregate read (AVG)": lambda: c.read(
            [tag], start=start.isoformat(), end=end.isoformat(), read_type=ReaderType.AVG
        ),
    }
    failed = 0
    for name, fn in checks.items():
        try:
            print(f"OK    {name}: {fn()}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")

print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
