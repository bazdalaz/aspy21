# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial project structure
- AspenClient with REST API support
- Support for analog, discrete, and text tags
- Unified pandas DataFrame output
- Built-in caching with SQLite
- Automatic retry logic with tenacity
- Type annotations and type checking
- Comprehensive test suite
- GitHub Actions CI/CD pipeline
- MIT License

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
