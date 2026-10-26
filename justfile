# justfile for aspy21 project automation
# Install just: https://just.systems/

# List all available commands
default:
    @just --list

# Install the versions in uv.lock (fails if uv.lock is out of date with pyproject.toml)
install:
    uv sync --locked --all-extras

# Install pre-commit hooks
setup-hooks:
    uv run pre-commit install

# Run all tests with coverage
test:
    uv run pytest

# Run tests with verbose output
test-verbose:
    uv run pytest -vv

# Run specific test file
test-file file:
    uv run pytest {{file}} -v

# Run linter (ruff check)
lint:
    uv run ruff check .

# Run linter and auto-fix issues
lint-fix:
    uv run ruff check --fix .

# Format code with ruff
format:
    uv run ruff format .

# Check formatting without making changes
format-check:
    uv run ruff format --check .

# Run type checking with pyright
typecheck:
    uv run pyright

# Run all quality checks (lint, format, typecheck)
check: lint format-check typecheck

# Run all checks and tests
ci: check test

# Clean build artifacts and cache
clean:
    rm -rf build/ dist/ *.egg-info/ .pytest_cache/ .ruff_cache/ .mypy_cache/ htmlcov/ .coverage
    find . -type d -name __pycache__ -exec rm -rf {} +

# Build distribution packages
build: clean
    uv build

# Build and check distribution
build-check: build
    uv run twine check dist/*

# Upload to TestPyPI (reads credentials from .env)
publish-test: build-check
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -f .env ]; then
        source <(grep -v '^#' .env | grep -E 'PYPI_TEST_' | sed 's/^/export /')
        export TWINE_USERNAME="${PYPI_TEST_USERNAME}"
        export TWINE_PASSWORD="${PYPI_TEST_TOKEN}"
    fi
    uv run twine upload --repository testpypi dist/*

# Upload to production PyPI (reads credentials from .env)
publish: build-check
    #!/usr/bin/env bash
    set -euo pipefail
    echo "⚠️  WARNING: Publishing to production PyPI!"
    echo "Press Ctrl+C to cancel, or Enter to continue..."
    read
    if [ -f .env ]; then
        source <(grep -v '^#' .env | grep -E '^PYPI_USERNAME=|^PYPI_TOKEN=' | sed 's/^/export /')
        export TWINE_USERNAME="${PYPI_USERNAME}"
        export TWINE_PASSWORD="${PYPI_TOKEN}"
    fi
    uv run twine upload dist/*

# Run pre-commit on all files
pre-commit:
    uv run pre-commit run --all-files

# Update pre-commit hooks
update-hooks:
    uv run pre-commit autoupdate

# Install development dependencies with uv
dev-install: install setup-hooks
    @echo "Development environment ready!"

# Show current version (from git tags)
version:
    @uv run python -c "from setuptools_scm import get_version; print(get_version())"

# Show next version for different bump types
version-next:
    #!/usr/bin/env -S uv run python
    import re
    from setuptools_scm import get_version

    current = get_version()
    # Remove .dev suffix if present
    current = re.sub(r'\.dev.*', '', current)
    # Parse version
    match = re.match(r'(\d+)\.(\d+)\.(\d+)((?:a|b|rc)(\d+))?', current)
    if match:
        major, minor, patch, pre, pre_num = match.groups()
        major, minor, patch = int(major), int(minor), int(patch)
        pre_num = int(pre_num) if pre_num else 0

        print(f"Current: {current}")
        print(f"\nNext versions:")
        print(f"  major:   v{major + 1}.0.0")
        print(f"  minor:   v{major}.{minor + 1}.0")
        print(f"  patch:   v{major}.{minor}.{patch + 1}")
        if pre:
            print(f"  {pre[:-1]}:      v{major}.{minor}.{patch}{pre[:-1]}{pre_num + 1}")
        else:
            print(f"  beta:    v{major}.{minor}.{patch + 1}b1")
            print(f"  rc:      v{major}.{minor}.{patch + 1}rc1")

# Bump version (create git tag)
# Usage: just bump <major|minor|patch|beta|rc|release> [--yes] [--push]
bump PART *ARGS:
    uv run python scripts/bump_version.py {{PART}} {{ARGS}}

# Create a git tag manually
# Usage: just tag v0.1.0b9
tag TAG:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Creating tag: {{TAG}}"
    git tag -a {{TAG}} -m "Release {{TAG}}"
    echo "✓ Tag created"
    echo "Push with: git push && git push --tags"
