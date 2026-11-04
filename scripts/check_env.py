"""Quick sanity check that Sky's dependencies are installed."""
from __future__ import annotations

import sys
from importlib import metadata

REQUIRED = ("PySide6-Essentials", "httpx", "psutil", "pytest")


def main() -> int:
    print(f"Python {sys.version.split()[0]}")
    failed = False

    for name in REQUIRED:
        try:
            print(f"  {name:<24} {metadata.version(name)}")
        except metadata.PackageNotFoundError:
            print(f"  {name:<24} MISSING")
            failed = True

    try:
        from PySide6 import QtWidgets  # noqa: F401

        print(f"  {'PySide6 QtWidgets':<24} import OK")
    except Exception as exc:
        print(f"  {'PySide6 QtWidgets':<24} import FAILED: {exc}")
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
