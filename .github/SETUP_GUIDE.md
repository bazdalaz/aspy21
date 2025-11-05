# Development Setup Guide

This guide will help you set up your development environment for the aspy21 project.

## Prerequisites

- Python 3.9+ installed
- [uv](https://github.com/astral-sh/uv) package manager
- [just](https://just.systems/) task runner (optional but recommended)

## Quick Start

### 1. Install uv (if not already installed)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Install dependencies

```bash
uv pip install -e ".[dev]"
```

### 3. Setup pre-commit hooks

```bash
pre-commit install
```

## Available Commands

If you have `just` installed, you can use these convenient commands:

```bash
just install          # Install dependencies
just setup-hooks      # Setup pre-commit hooks
just test             # Run tests with coverage
just lint             # Run linter
just lint-fix         # Auto-fix linting issues
just format           # Format code
just typecheck        # Run type checking
just check            # Run all checks (lint, format, typecheck)
just ci               # Run all checks + tests (same as CI)
just clean            # Clean build artifacts
just build            # Build distribution packages
```

Or use the tools directly:

```bash
# Testing
pytest
pytest -vv  # verbose
pytest tests/test_client.py  # specific file

# Linting & Formatting
ruff check .
ruff check --fix .
ruff format .

# Type Checking
pyright

# Pre-commit (run all hooks)
pre-commit run --all-files
```

## Project Structure

```
aspy21/
├── src/aspy21/          # Main package code
│   ├── __init__.py
│   ├── client.py        # AspenClient implementation
│   ├── models.py        # Data models (ReaderType, etc.)
│   ├── utils.py         # Utility functions
│   ├── query_builder.py # Query building utilities
│   └── readers/         # Reader strategy classes
├── tests/               # Test suite
├── .github/workflows/   # CI/CD pipelines
├── docs/                # Documentation
├── pyproject.toml       # Project configuration
├── justfile             # Task automation
└── .pre-commit-config.yaml  # Pre-commit hooks

```

## Modern Toolchain (2025)

This project uses the latest Python tooling:

- **Package Manager**: `uv` (10-100x faster than pip)
- **Linter + Formatter**: `ruff` (replaces black, flake8, isort)
- **Type Checker**: `pyright` (fast, actively maintained)
- **Test Runner**: `pytest` with coverage
- **Task Runner**: `just` (optional, for convenience)
- **Pre-commit**: Automated code quality checks

## CI/CD

GitHub Actions automatically:
- Tests on Python 3.9, 3.10, 3.11, 3.12, 3.13
- Runs linting, formatting, and type checking
- Reports test coverage to Codecov
- Publishes to PyPI on version tags

## Publishing to PyPI

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Create and push a git tag:
   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```
4. GitHub Actions will automatically build and publish to PyPI

## Tips

- Always run `just check` before committing
- Pre-commit hooks will catch issues automatically
- Use `just ci` to run the same checks as GitHub Actions locally
- Keep CHANGELOG.md updated with each change
