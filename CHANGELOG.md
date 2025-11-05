# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Transport abstraction via dependency injection of `httpx.Client`
- Reader strategy pattern for better modularity and extensibility
- Comprehensive GitHub issue templates (bug report, feature request, documentation)
- GitHub pull request template
- Enhanced CONTRIBUTING.md with detailed guidelines and examples
- Additional README badges (codecov, ruff, pyright)
- Test coverage for `utils.chunked` function

### Changed
- **BREAKING**: Refactored `AspenClient.read` method from ~344 lines to ~45 lines using strategy pattern
- Split read logic into separate reader classes:
  - `SnapshotReader` for current value reads
  - `SqlHistoryReader` for batched SQL queries
  - `XmlHistoryReader` for per-tag XML queries
  - `DataFormatter` for output formatting
- Improved testability through dependency injection

### Removed
- Unused `SmartCache` module (was placeholder, never integrated)

### Fixed
- Code organization and maintainability improvements
- Better separation of concerns in client architecture

## [0.1.0] - 2025-10-29

### Added
- Initial release
- REST-only backend for Aspen InfoPlus.21
- Support for RAW, INT, SNAPSHOT, AVG reader types
- DataFrame output with optional status column
- Transparent batching and connection management
- 100% type-annotated code

[Unreleased]: https://github.com/bazdalaz/aspy21/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/bazdalaz/aspy21/releases/tag/v0.1.0
