#!/usr/bin/env python3
"""
Pull-request rule: a PR that changes product code must also add or change
BOTH a unit test (tests/unit/) and an integration test (tests/integration/).

Product code = anything under app/ or web/. Docs, scripts, CI and config
changes don't need tests.

Usage (CI runs this on every pull request):
    python scripts/ci/check_tests_included.py --base origin/main
"""
from __future__ import annotations

import argparse
import subprocess
import sys

CODE_PREFIXES = ("app/", "web/")
CODE_SUFFIXES = (".py", ".js", ".css", ".html")


def is_code(path: str) -> bool:
    return path.startswith(CODE_PREFIXES) and path.endswith(CODE_SUFFIXES) and "/README" not in path


def is_test(path: str, kind: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.startswith(f"tests/{kind}/") and name.startswith("test_") and name.endswith(".py")


def missing_tests(changed: list[str]) -> list[str]:
    """Which test kinds are missing for this set of changed files ([] = OK)."""
    if not any(is_code(p) for p in changed):
        return []
    return [kind for kind in ("unit", "integration") if not any(is_test(p, kind) for p in changed)]


def changed_files(base: str) -> list[str]:
    out = subprocess.run(["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD"],
                         check=True, capture_output=True, text=True).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="origin/main", help="branch the PR merges into")
    args = ap.parse_args()

    changed = changed_files(args.base)
    code = [p for p in changed if is_code(p)]
    missing = missing_tests(changed)
    print(f"Changed files: {len(changed)} ({len(code)} product code)")
    if not missing:
        print("OK: tests are included." if code else "OK: no product code changed, tests not required.")
        return 0
    print("\nThis pull request changes product code but is missing:")
    for kind in missing:
        article = "an" if kind[0] in "aeiou" else "a"
        print(f"  - {article} {kind} test: add or update a tests/{kind}/test_*.py file")
    print("\nCode changed:\n  " + "\n  ".join(code[:20]))
    print("\nSee CONTRIBUTING.md → Tests. Unit tests check logic without a network; integration tests "
          "run the real server, adapters against simulated devices, or the UI in a browser.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
