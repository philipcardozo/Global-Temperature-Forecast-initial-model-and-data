"""Command-line interface for the forecast system."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from gtf import __version__
from gtf.run_id import RunId


def _validate_run_id(
    arguments: argparse.Namespace,
) -> int:
    run_id = RunId.parse(str(arguments.run_id))

    print(run_id.value)
    print(run_id.initialization_utc.isoformat())

    return 0


def _audit(
    arguments: argparse.Namespace,
) -> int:
    run_id = RunId.parse(str(arguments.run_id))

    script = Path(str(arguments.script))

    if not script.is_file():
        raise FileNotFoundError(f"Readiness audit script not found: {script}")

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--run-id",
            run_id.value,
        ],
        check=False,
    )

    return result.returncode


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line parser."""

    parser = argparse.ArgumentParser(
        prog="gtf",
        description=("Global Temperature Forecast processing and verification system."),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=(f"%(prog)s {__version__}"),
    )

    subparsers = parser.add_subparsers(
        dest="command",
    )

    validate_parser = subparsers.add_parser(
        "validate-run-id",
        help=("Validate and normalize a forecast run identifier."),
    )

    validate_parser.add_argument(
        "run_id",
        help="Run identifier in YYYYMMDD_CCz format.",
    )

    validate_parser.set_defaults(
        handler=_validate_run_id,
    )

    audit_parser = subparsers.add_parser(
        "audit",
        help=("Run the existing multi-cycle readiness audit."),
    )

    audit_parser.add_argument(
        "--run-id",
        required=True,
        help="Run identifier in YYYYMMDD_CCz format.",
    )

    audit_parser.add_argument(
        "--script",
        default="audit_multicycle_readiness.py",
        help=("Path to the compatibility audit script."),
    )

    audit_parser.set_defaults(
        handler=_audit,
    )

    return parser


def main(
    argv: Sequence[str] | None = None,
) -> int:
    """Execute the command-line interface."""

    parser = build_parser()
    arguments = parser.parse_args(argv)

    handler = getattr(
        arguments,
        "handler",
        None,
    )

    if handler is None:
        parser.print_help()
        return 0

    try:
        result = handler(arguments)
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))
        return 2

    if not isinstance(result, int):
        raise TypeError("CLI command handler must return an integer.")

    return result
