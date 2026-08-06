"""Harmless subprocess fixture for executor tests."""

from __future__ import annotations

import argparse


def main() -> int:
    """Print a message and return the requested exit code."""

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--message",
        required=True,
    )

    parser.add_argument(
        "--exit-code",
        type=int,
        default=0,
    )

    arguments = parser.parse_args()

    print(arguments.message)

    return int(arguments.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
