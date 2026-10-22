"""Checks of the code examples in README.md and in public docstrings."""

from __future__ import annotations

import ast
import doctest
import inspect
import re
from pathlib import Path

import pytest

import aspy21

README = Path(__file__).parent.parent / "README.md"


def readme_blocks() -> list[tuple[int, str]]:
    """Return (line number, code) for each ```python block in the README."""
    text = README.read_text(encoding="utf-8")
    return [
        (text.count("\n", 0, match.start()) + 2, match.group(1))
        for match in re.finditer(r"```python\n(.*?)```", text, re.DOTALL)
    ]


def docstring_examples() -> list[tuple[str, str]]:
    """Return (qualified name, code) for each docstring with >>> examples."""
    parser = doctest.DocTestParser()
    examples = []
    for name in aspy21.__all__:
        obj = getattr(aspy21, name)
        members = [(name, obj)]
        if inspect.isclass(obj):
            members += [(f"{name}.{attr}", value) for attr, value in vars(obj).items()]
        for qualname, member in members:
            doc = inspect.getdoc(member) if callable(member) else None
            if doc and ">>>" in doc:
                code = "".join(example.source for example in parser.get_examples(doc))
                examples.append((qualname, code))
    return examples


def calls(tree: ast.AST, name: str) -> list[ast.Call]:
    """Return calls of a function or method with this name."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called == name:
                found.append(node)
    return found


def check_example(code: str, where: str) -> None:
    tree = ast.parse(code, filename=where)

    for call in calls(tree, "AspenClient"):
        keywords = {k.arg for k in call.keywords}
        assert "datasource" in keywords, f"{where}: AspenClient() without datasource"

    for method in ("read", "search"):
        for call in calls(tree, method):
            # start, end and the other options are keyword-only
            assert len(call.args) <= 1, f"{where}: {method}() with positional options"


def test_readme_has_examples():
    assert len(readme_blocks()) > 20


@pytest.mark.parametrize(("line", "code"), readme_blocks(), ids=lambda v: str(v)[:8])
def test_readme_example(line, code):
    check_example(code, f"README.md:{line}")


def test_docstrings_have_examples():
    names = [name for name, _ in docstring_examples()]
    assert "AspenClient.read" in names
    assert "AspenClient.__init__" in names


@pytest.mark.parametrize(("name", "code"), docstring_examples(), ids=lambda v: str(v)[:30])
def test_docstring_example(name, code):
    check_example(code, name)


def test_package_is_typed():
    """PEP 561 marker, so type checkers use the package's annotations."""
    assert (Path(aspy21.__file__).parent / "py.typed").is_file()
