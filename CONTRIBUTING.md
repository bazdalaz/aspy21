# Contributing to aspy21

Thank you for your interest in contributing to aspy21! This guide will help you get started.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Code Quality](#code-quality)
- [Submitting Changes](#submitting-changes)
- [Release Process](#release-process)

## Code of Conduct

This project adheres to a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Getting Started

### Ways to Contribute

- 🐛 **Report bugs**: Open an issue using the bug report template
- ✨ **Suggest features**: Open an issue using the feature request template
- 📚 **Improve documentation**: Help us make our docs clearer
- 🔧 **Fix issues**: Check our [issue tracker](https://github.com/bazdalaz/aspy21/issues)
- ✅ **Write tests**: Improve our test coverage
- 🎨 **Code improvements**: Refactoring, performance optimizations

### First Time Contributors

Look for issues labeled `good-first-issue` or `help-wanted` in our [issue tracker](https://github.com/bazdalaz/aspy21/issues).

## Development Setup

### Prerequisites

- Python 3.9 or higher
- [uv](https://github.com/astral-sh/uv) package manager (recommended)
- [just](https://just.systems/) task runner (optional but recommended)
- Git

### Setup Steps

1. **Fork and clone the repository**

   ```bash
   git clone https://github.com/YOUR_USERNAME/aspy21.git
   cd aspy21
   ```

2. **Install uv (if not already installed)**

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. **Create a virtual environment and install dependencies**

   ```bash
   # Using uv (recommended)
   uv pip install -e ".[dev]"

   # Or using standard pip
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   ```

4. **Install pre-commit hooks**

   ```bash
   pre-commit install
   ```

   This will automatically run code quality checks before each commit.

## Making Changes

### Branch Naming

Create a branch with a descriptive name:

- `feature/add-caching-support` - for new features
- `fix/connection-timeout` - for bug fixes
- `docs/update-readme` - for documentation
- `refactor/reader-classes` - for refactoring
- `test/add-utils-tests` - for test improvements

```bash
git checkout -b feature/your-feature-name
```

### Code Style

This project uses modern Python tooling:

- **Formatter**: [Ruff](https://docs.astral.sh/ruff/) (replaces Black)
- **Linter**: Ruff (replaces flake8, isort, etc.)
- **Type Checker**: [Pyright](https://github.com/microsoft/pyright)

#### Style Guidelines

- Use type hints for all function signatures
- Write descriptive docstrings (Google style)
- Keep functions focused and under 50 lines when possible
- Use descriptive variable names
- Follow PEP 8 conventions
- Maximum line length: 100 characters

#### Example

```python
def read_tags(
    tags: list[str],
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Read process data for multiple tags.

    Args:
        tags: List of tag names to retrieve
        start: Start timestamp in ISO format
        end: End timestamp in ISO format

    Returns:
        DataFrame with timestamp index and tag columns

    Raises:
        ValueError: If tags list is empty
    """
    if not tags:
        raise ValueError("At least one tag is required")
    ...
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=aspy21 --cov-report=html

# Run specific test file
pytest tests/test_client.py

# Run specific test
pytest tests/test_client.py::TestAspenClient::test_read_basic

# Run in verbose mode
pytest -vv
```

### Writing Tests

- Write tests for all new features
- Aim for >90% code coverage
- Use descriptive test names: `test_<method>_<scenario>_<expected_result>`
- Use fixtures for common setup
- Mock external dependencies (HTTP calls, etc.)

#### Example Test

```python
def test_read_with_invalid_tags_raises_error(
    aspen_client: AspenClient,
) -> None:
    """Test that read() raises ValueError for empty tag list."""
    with pytest.raises(ValueError, match="At least one tag is required"):
        aspen_client.read([])
```

## Code Quality

### Pre-commit Checks

Pre-commit hooks run automatically on `git commit`. To run manually:

```bash
pre-commit run --all-files
```

### Manual Checks

```bash
# Format code
ruff format .

# Lint and auto-fix
ruff check --fix .

# Type checking
pyright

# Run all checks (same as CI)
just ci  # If using just
```

### Quality Standards

All contributions must:

- ✅ Pass all tests
- ✅ Pass Ruff formatting and linting
- ✅ Pass Pyright type checking
- ✅ Maintain or improve code coverage
- ✅ Include docstrings for public APIs
- ✅ Update relevant documentation

## Submitting Changes

### Commit Messages

Write clear, descriptive commit messages:

```
type: Brief summary (50 chars or less)

More detailed explanation if needed (wrap at 72 chars).
Explain what changed and why, not how.

- Bullet points are okay
- Use present tense ("Add feature" not "Added feature")
- Reference issues: "Fixes #123"
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `test`: Test additions/updates
- `refactor`: Code refactoring
- `perf`: Performance improvements
- `chore`: Maintenance tasks
- `style`: Code style changes (formatting)

### Pull Request Process

1. **Update your branch**

   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Push your changes**

   ```bash
   git push origin your-branch-name
   ```

3. **Open a Pull Request**

   - Use the PR template
   - Link related issues
   - Describe your changes clearly
   - Add screenshots/examples if relevant

4. **Code Review**

   - Address reviewer feedback
   - Keep discussions constructive
   - Update your PR as needed

5. **Merge**

   - Squash commits if requested
   - Ensure CI passes
   - Wait for maintainer approval

### Review Checklist

Before requesting review, ensure:

- [ ] All tests pass locally
- [ ] Code follows style guidelines
- [ ] Documentation is updated
- [ ] CHANGELOG.md is updated
- [ ] Commit messages are clear
- [ ] PR description is complete

## Release Process

Releases are automated via GitHub Actions:

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Create and push a git tag:
   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```
4. GitHub Actions will automatically:
   - Run all tests
   - Build distribution packages
   - Publish to PyPI

## Getting Help

- 📖 Check our [documentation](README.md)
- 💬 Ask questions in [Discussions](https://github.com/bazdalaz/aspy21/discussions)
- 🐛 Report bugs via [Issues](https://github.com/bazdalaz/aspy21/issues)
- 📧 Contact maintainers (see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md))

## Recognition

Contributors are recognized in:
- GitHub contributors page
- CHANGELOG.md (for significant contributions)
- Release notes

Thank you for contributing to aspy21! 🎉
