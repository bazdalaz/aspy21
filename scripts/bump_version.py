#!/usr/bin/env python3
"""Version bumping script for aspy21."""

import re
import subprocess
import sys

from setuptools_scm import get_version


def main():
    if len(sys.argv) < 2:
        print("Usage: bump_version.py <major|minor|patch|beta|rc|release> [--push] [--yes]")
        sys.exit(1)

    part = sys.argv[1]
    push = "--push" in sys.argv[2:]
    auto_yes = "--yes" in sys.argv[2:]

    current = get_version()
    # Remove .dev suffix if present
    current = re.sub(r"\.dev.*", "", current)

    # Parse current version
    match = re.match(r"(\d+)\.(\d+)\.(\d+)((?:a|b|rc)(\d+))?", current)
    if not match:
        print(f"Error: Cannot parse version: {current}", file=sys.stderr)
        sys.exit(1)

    major, minor, patch, pre, pre_num = match.groups()
    major, minor, patch = int(major), int(minor), int(patch)
    pre_num = int(pre_num) if pre_num else 0
    pre_type = pre[:-1] if pre else None  # 'a', 'b', 'rc', or None

    # Calculate new version
    if part == "major":
        new_version = f"v{major + 1}.0.0"
    elif part == "minor":
        new_version = f"v{major}.{minor + 1}.0"
    elif part == "patch":
        new_version = f"v{major}.{minor}.{patch + 1}"
    elif part == "beta":
        if pre_type == "b":
            new_version = f"v{major}.{minor}.{patch}b{pre_num + 1}"
        elif pre_type == "a":
            new_version = f"v{major}.{minor}.{patch}b1"
        else:
            new_version = f"v{major}.{minor}.{patch + 1}b1"
    elif part == "rc":
        if pre_type == "rc":
            new_version = f"v{major}.{minor}.{patch}rc{pre_num + 1}"
        elif pre_type in ("a", "b"):
            new_version = f"v{major}.{minor}.{patch}rc1"
        else:
            new_version = f"v{major}.{minor}.{patch + 1}rc1"
    elif part == "release":
        # Remove prerelease suffix
        new_version = f"v{major}.{minor}.{patch}"
    else:
        print(f"Error: Invalid part '{part}'", file=sys.stderr)
        print("Use: major, minor, patch, beta, rc, release", file=sys.stderr)
        sys.exit(1)

    print(f"Current version: {current}")
    print(f"New version:     {new_version}")

    # Check if tag already exists
    result = subprocess.run(
        ["git", "tag", "-l", new_version], capture_output=True, text=True, check=False
    )
    if result.stdout.strip():
        print(f"\nError: Tag {new_version} already exists!", file=sys.stderr)
        sys.exit(1)

    print()
    if not auto_yes:
        response = input("Create tag? [y/N]: ")
        if response.lower() != "y":
            print("Aborted.")
            sys.exit(0)

    # Create tag
    subprocess.run(["git", "tag", "-a", new_version, "-m", f"Release {new_version}"], check=True)
    print(f"✓ Created tag {new_version}")

    # Push if --push flag provided
    if push:
        print("\nPushing to remote...")
        subprocess.run(["git", "push"], check=True)
        subprocess.run(["git", "push", "--tags"], check=True)
        print("✓ Pushed to remote")
    else:
        print("\nPush with: git push && git push --tags")


if __name__ == "__main__":
    main()
