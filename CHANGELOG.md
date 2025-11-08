# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/bazdalaz/aspy21/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/bazdalaz/aspy21/releases/tag/v0.0.1
