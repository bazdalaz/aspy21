# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-26

First minor release. 0.1.x releases only add fixes; breaking changes go to 0.2.0 (see
Versioning in CONTRIBUTING.md). Tested against a production IP.21 server: row limits, tag
name case, time zones, retries, escaping and large reads.

### Changed (breaking)
- Requires Python 3.11 or newer; Python 3.9 and 3.10 are end of life. Tested on 3.11 - 3.15
- Requires pandas 2.2.2 or newer. Earlier pandas 2 releases fail to import with numpy 2,
  which pip installs alongside them
- `ReaderType`, `IncludeFields` and `OutputFormat` are `StrEnum`s: `str(ReaderType.RAW)` and
  f-strings give `"RAW"` instead of `"ReaderType.RAW"`. Comparisons with strings are unchanged
- Development tools moved from the `dev` extra to a `dev` dependency group (PEP 735):
  `uv sync`, or `pip install -e . --group dev` with pip 25.1+. `uv.lock` pins them for
  development and CI

### Performance
- RAW, INT and aggregate reads parse response timestamps in one call instead of one by
  one: parsing 120,000 history rows takes 0.2 s instead of 25 s
- Response bodies are no longer decoded to text just for DEBUG log messages that are
  not written

### Fixed
- The cache evicts the least recently used entry when full, as documented in its
  docstrings; it evicted the oldest entry even when that entry was in use. Replacing an
  entry in a full cache no longer evicts another one
- The warning for a tag that reaches its row limit shows the last time as server local
  time; it was labelled `+00:00` (UTC) although it is not

### Security
- `.env.example`, the examples and the scripts verify SSL certificates unless
  `ASPEN_VERIFY_SSL` is set to false (they turned verification off by default)

## [0.0.13] - 2026-10-25

### Fixed
- `invalidate_cache(tags=...)` ignores the letter case of tag names, as `read()` does
  since 0.0.11: `invalidate_cache(tags=["TAG1.PV"])` also removes a cached read of
  `tag1.pv`

## [0.0.12] - 2026-10-25

**Documentation release** - No code changes.

### Documentation
- README and the `read()` docstring say that tag names are case-insensitive and that
  results use the names as given
- Examples, tests and docstrings use generic tag names (`TAG1.PV`, `TEMP_201`, ...)

## [0.0.11] - 2026-10-25

### Fixed
- Tags requested in a different letter case than IP.21 stores them (e.g. `tag1.pv` for
  `TAG1.PV`) returned no data, with a "No data in SQL response" warning. IP.21 matches tag
  names regardless of case and returns the stored name, which the response parsers
  compared exactly. They now ignore case; columns, JSON `tag` fields and descriptions use
  the name as requested

## [0.0.10] - 2026-10-24

**Multi-tag read release** - Reads of several tags return every value: `limit` applies to
each tag, integer values are no longer dropped from JSON output, and repeated timestamps
are kept. The package is now typed for editors and type checkers, and server errors share
the new `AspenError` base class.

### Changed
- Errors reported by the Browse endpoint (search by tag name only) raise the new
  `AspenBrowseError` instead of a plain `ValueError`. Both it and `AspenSqlError` derive
  from the new `AspenError`, which derives from `ValueError`, so existing `ValueError` and
  `AspenSqlError` handlers keep working. Catch `AspenError` for errors from either endpoint
- A Browse response with an unexpected structure, or one that is not JSON, now raises
  `AspenBrowseError`. Previously an unexpected structure returned `[]`, reported as "no
  tags found"
- A SQL response that is not JSON now raises `AspenSqlError` (previously a `ValueError`,
  or a `JSONDecodeError` for aggregate reads). An aggregates response with an unexpected
  structure raises `AspenSqlError` instead of returning no data
- Errors raised to the caller are no longer also logged at ERROR level (failed searches,
  non-JSON responses); they are logged at DEBUG
- Passing `auth`, `timeout` or `verify_ssl` together with `http_client` logs a warning,
  since they are not applied to a provided client
- The history query sent `to="30   "` (with trailing spaces); it now sends `to="30"`. The
  DEBUG log no longer reports an unchanged row limit for single-tag reads
- Much smaller DEBUG logs for aggregate reads: the parser no longer logs every row and
  the reader no longer logs the full response body (a 500-character preview remains).
  A 1,440-row read went from about 2,900 log lines to 20
- Rows the aggregates parser skips (no timestamp, no value, no tag name, invalid
  structure) are reported in one warning per tag with a count, instead of one warning
  per row. Per-tag parse summaries moved from INFO to DEBUG

### Fixed
- `limit` was not applied per tag in RAW and INT reads of several tags. The server's row
  limit covers the whole result, which it returns grouped by tag, so once the first tag
  had more than `limit` values it filled the result and later tags came back with fewer
  values or none (confirmed on a production server). Tags cut short are now read again
  one at a time. Reads that stay below the limit still take a single query
- A tag that returns `limit` rows now logs a warning, since its later values in the range
  were not read
- JSON output (the default) dropped every value stored as an integer, so integer-valued
  tags returned no data. Integer and status values are now returned, and values are plain
  Python types (`1`, `2.5`) instead of numpy scalars. Integer values and statuses stay
  integers when read together with other tags, also when the tags have values at
  different timestamps
- Reading several tags failed with `InvalidIndexError` when one tag had two values at the
  same timestamp and another tag did not, and a tag with one value at that timestamp was
  repeated on each of the other tag's rows. Every value is now kept once

### Added
- `examples/multi_tag_merge.py` checks how multi-tag reads are merged: offline with
  mocked responses (gaps, duplicate timestamps, integers), then against the server in `.env`
- `scripts/check_row_limits.py` checks row limits and RAW intervals against the server in
  `.env`
- The package now ships a `py.typed` marker (PEP 561), so type checkers such as mypy use
  its annotations instead of treating it as untyped
- Typed overloads for `read()` and `search()`: editors and type checkers infer
  `pd.DataFrame` for `output=OutputFormat.DATAFRAME`, `list[dict]` for JSON output and
  `list[str]` for a tag name search, instead of a union that needed `isinstance` checks

### Documentation
- README examples used a `base_url` without `AtProcessDataREST.dll`, and several omitted
  the `datasource` that reads and searches require. Docstring examples also passed
  `start`/`end` positionally, which raises `TypeError`. All examples are now checked by tests
- Corrected the caching documentation: snapshot reads are not cached, and `ttl_snapshot`
  and `ttl_metadata` have no effect
- Documented the layout of multi-tag results (gaps, `<tag>_status` columns, repeated
  timestamps), logging with `configure_logging()`, the `http_client` option, and the
  errors `read()` and `search()` raise

## [0.0.9] - 2026-10-22

**Retry release** - Transient request failures are retried, and `configure_logging()`
applies to the whole library.

### Added
- Automatic retries of transient failures, controlled by the new `retries` option on
  `AspenClient` (default 2, so up to 3 attempts; `retries=0` disables them). Connection
  errors, connect timeouts and HTTP 429/502/503/504 are retried with exponential backoff
  (0.5s up to 8s) or the server's `Retry-After` (up to 30s). Read timeouts, other HTTP
  errors and SQL errors are not retried. Each retry is logged as a warning

### Changed
- A request that fails with a transient error is now repeated before the error is raised,
  so such failures take longer to surface. Pass `retries=0` for the previous behavior

### Fixed
- `configure_logging()` only configured the client module's logger. Messages from the
  readers, retries and cache were printed without the configured format, ignored the
  configured level (retry warnings showed even at `ERROR`), and their DEBUG/INFO messages
  never appeared. It now configures the `aspy21` package logger
- With a custom `http_client`, the debug log showed the `timeout` and `verify_ssl`
  arguments, which are not applied to such a client. It now logs the client's own timeout

## [0.0.8] - 2026-10-22

**Cache correctness release** - Cache hits now always return the data the request asked
for, and `invalidate_cache()` removes matching entries.

### Fixed
- Cached `read()` results were returned for requests that should give a different result:
  a cached JSON result was served for a DataFrame request (and the reverse), results
  ignored `limit` and tag order, and clients sharing an `AspenCache` served each other's
  data across servers, datasources and `server_timezone` settings. Cache keys now include
  every argument and client setting that affects the result
- Search results cached through a shared `AspenCache` are no longer shared between
  clients on different servers or datasources
- Modifying a DataFrame or list returned by `read()` or `search()` changed what later
  cache hits returned. The cache now stores and returns copies
- `invalidate_cache(tags=..., start=..., end=...)` never removed anything. It now removes
  cached reads from this client's server and datasource that include any of the given
  tags and match the given start and end

### Added
- `AspenCache.invalidate_where(predicate)` removes every entry for which
  `predicate(operation, params)` is true

## [0.0.7] - 2026-10-22

**Time zone release** - Timestamps are now consistent across read types and match the
server's clock.

### Changed
- Returned timestamps are naive server-local times by default; history and aggregate
  timestamps no longer carry a `+00:00` offset, and snapshot timestamps are no longer UTC.
  Pass `server_timezone` to get timezone-aware timestamps

### Fixed
- Timestamps from history and aggregate reads were labelled UTC (`+00:00`) although IP.21
  returns server local time, while snapshot reads used the client's UTC clock. All reads
  now return server local time, naive by default

### Added
- `server_timezone` option on `AspenClient` (e.g. `"Europe/Berlin"`): returned timestamps
  are timezone-aware in that zone, and timezone-aware `start`/`end` values are converted
  to it. Use `server_timezone="UTC"` for a server that returns real UTC times

### Documentation
- Removed claims of automatic request retries, which were never implemented
- Documented `AspenSqlError` handling and that aggregates are stamped at period end

## [0.0.6] - 2026-10-22

**Error handling release** - SQL errors are now raised instead of being returned as empty
data, and aggregate reads send timestamps in a format IP.21 accepts.

### Changed
- SQL errors reported by the server now raise `AspenSqlError` (a `ValueError` subclass).
  Previously most were logged and the read or search returned no data

### Fixed
- SQL errors returned by IP.21 with HTTP 200 (`AtPD_ErrorCode` records, or `result.er` in
  search responses) are now raised as `AspenSqlError` instead of being reported as "no data"
- Snapshot reads of unknown tags no longer fail with "Failed to parse JSON response" when
  the server returns an empty body; they return no data
- Response parsers no longer turn unexpected failures into empty results
- Empty read results are no longer cached, so a transient empty response is not pinned
  for the historical TTL (24h by default)
- Aggregate reads (AVG, MIN, MAX, RNG) sent `start`/`end` unconverted, which IP.21 rejects
  for ISO timestamps (`Invalid TIMESTAMP value`). The error was hidden, so these reads
  silently returned no data. Timestamps are now converted like history reads
- Timestamps in queries used locale-dependent month names (e.g. `Okt` on a German
  system), which IP.21 cannot parse. Month names are now always English
- Aggregate values of exactly 0 (e.g. a range or average of zero) were dropped as
  "missing" because of a truthiness check; they are now returned

### Added
- `AspenSqlError` exception (subclass of `ValueError`, so existing handlers keep working)

## [0.0.5] - 2026-10-21

**Security Release** - Fixes SQL and XML injection in query building. Upgrading is recommended.

### Security
- Escape single quotes in all SQL string literals (tag names, search patterns, timestamps).
  Previously a tag or search value containing `'` could alter the SQLplus query,
  e.g. `search(description="x' or '1'='1")`
- Escape the datasource name in the XML request attribute
- Reject query values containing `]]>`, which could break out of the CDATA section
- Coerce `interval` and `limit` to integers before building queries

### Removed
- Unused internal `XmlHistoryResponseParser` and `cached()` decorator (never exported)

### Added
- `scripts/smoke_test.py` for checking a build against a live IP.21 server

## [0.0.2] - 2025-11-08

**Performance & Caching Release** - Adds intelligent caching layer to reduce API load and improve performance.

### Added

**Caching System**
- Intelligent caching layer that reduces API load by 60-80% for typical workloads
- 10-100x performance improvement for repeated queries
- TTL (Time-To-Live) + LRU (Least Recently Used) eviction strategy
- Thread-safe cache implementation for concurrent requests
- Smart caching: historical data cached longer (24h) than current data (1min)
- Three cache modes:
  - `cache=True` - Enable with sensible defaults
  - `cache=CacheConfig(...)` - Custom TTLs and size limits
  - `cache=AspenCache()` - Share cache across multiple clients

**Cache Management**
- `get_cache_stats()` - View cache performance metrics (hits, misses, hit rate, size)
- `clear_cache()` - Remove all cached entries
- `invalidate_cache()` - Remove specific entries by tags/time range

**Examples & Documentation**
- New `examples/caching_example.py` with 4 comprehensive demonstrations
- Complete caching documentation in README.md
- 30 cache-specific tests with 88% coverage

### Fixed
- Cache retrieval logic in `read()` method (was only setting, not getting)
- `NameError` where `cache_key_params` was undefined

### Technical Details
- `CacheConfig` class for configurable TTLs and cache size
- `AspenCache` class with thread-safe operations
- Automatic cache key generation from query parameters
- Separate TTLs for historical (24h), search (1h), and snapshot (1min) operations

### Performance Impact
- First query: Normal API latency
- Cached queries: 10-100x faster (typically <10ms vs 100-1000ms)
- Memory efficient: LRU eviction prevents unbounded growth
- Default max size: 1000 entries

## [0.0.1] - 2025-11-08

**Initial stable release** - Production-ready Python client for Aspen InfoPlus.21 historian.

### Features

**Data Reading**
- Read historical time-series data with 7 reader types: RAW, INT, SNAPSHOT, AVG, MIN, MAX, RNG
- Aggregates with interval-based statistics (10-minute averages, hourly min/max, etc.)
- Multiple output formats: pandas DataFrame, JSON list, or dict
- Configurable time ranges and row limits (up to 100,000 rows per query)
- Optional status values and tag descriptions in results

**Tag Search & Discovery**
- Wildcard search with `*` and `?` patterns
- Filter by tag name and/or description
- Hybrid mode: search and read data in a single operation
- Return tag names only or include full metadata (description, maptype)
- Configurable result limits (default: 10,000 tags)

**Developer Experience**
- Context manager support for automatic resource cleanup
- 100% type-annotated with pyright strict mode
- pandas integration for time-series analysis
- Automatic retry logic for network resilience
- Comprehensive error handling with descriptive messages
- Flexible logging (DEBUG, INFO, WARNING, ERROR levels)

**Architecture**
- Clean reader strategy pattern for extensibility
- Dependency injection for improved testability
- SQL-based queries for optimal performance
- httpx for modern async-ready HTTP client
- Response parsers handle malformed data gracefully

**Quality & Testing**
- 88% test coverage with 105 tests across 8 test modules
- All error paths tested (HTTP errors, JSON parsing, network failures)
- CI/CD ready with ruff, pyright, and pytest
- Pre-commit hooks for code quality
- Modern Python packaging (pyproject.toml, src layout)

**Documentation**
- Complete README with installation guide and API reference
- Working examples for all major use cases
- CONTRIBUTING.md with development workflow
- CODE_OF_CONDUCT.md and SECURITY.md
- Detailed docstrings following Google style

### Requirements

- Python 3.9+
- httpx >= 0.27
- pandas >= 2.0
- tenacity >= 9.0

### Getting Started

```python
from aspy21 import AspenClient, ReaderType

with AspenClient(
    base_url="http://server/ProcessData/AtProcessDataREST.dll",
    auth=("username", "password"),
    datasource="IP21"
) as client:
    # Read 10-minute averages
    df = client.read(
        tags=["TEMP01", "PRESSURE02"],
        start="2025-01-15 08:00:00",
        end="2025-01-15 09:00:00",
        read_type=ReaderType.AVG,
        interval=600
    )
    print(df)
```

### Installation

```bash
pip install aspy21
```

### Examples

- `examples/basic_usage.py` - Basic authentication and data reading with .env configuration
- `examples/search_and_read.py` - Tag search, filtering, and hybrid mode demonstrations

### Notes

This is the first stable release. The API is considered stable and follows semantic versioning. Breaking changes will only occur in major version updates (e.g., 1.0.0).

[Unreleased]: https://github.com/bazdalaz/aspy21/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/bazdalaz/aspy21/compare/v0.0.13...v0.1.0
[0.0.13]: https://github.com/bazdalaz/aspy21/compare/v0.0.12...v0.0.13
[0.0.12]: https://github.com/bazdalaz/aspy21/compare/v0.0.11...v0.0.12
[0.0.11]: https://github.com/bazdalaz/aspy21/compare/v0.0.10...v0.0.11
[0.0.10]: https://github.com/bazdalaz/aspy21/compare/v0.0.9...v0.0.10
[0.0.9]: https://github.com/bazdalaz/aspy21/compare/v0.0.8...v0.0.9
[0.0.8]: https://github.com/bazdalaz/aspy21/compare/v0.0.7...v0.0.8
[0.0.7]: https://github.com/bazdalaz/aspy21/compare/v0.0.6...v0.0.7
[0.0.6]: https://github.com/bazdalaz/aspy21/compare/v0.0.5...v0.0.6
[0.0.5]: https://github.com/bazdalaz/aspy21/compare/v0.0.2...v0.0.5
[0.0.2]: https://github.com/bazdalaz/aspy21/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/bazdalaz/aspy21/releases/tag/v0.0.1
