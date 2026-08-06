"""Command-line interface for the forecast system."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from gtf import __version__
from gtf.orchestration.config import (
    load_pipeline_config,
)
from gtf.orchestration.executor import (
    execute_plan,
)
from gtf.orchestration.planner import (
    PlannedStage,
    build_plan,
)
from gtf.orchestration.state import (
    write_execution_state,
    write_plan_state,
)
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


def _print_plan(
    stages: tuple[PlannedStage, ...],
) -> None:
    """Print a rendered pipeline plan."""

    for position, stage in enumerate(
        stages,
        start=1,
    ):
        command = " ".join(stage.command)

        requirement = "required" if stage.required else "optional"

        print(f"{position:02d}. [{stage.category}] {stage.name} ({requirement})")

        print(f"    {command}")


def _run_pipeline(
    arguments: argparse.Namespace,
) -> int:
    run_id = RunId.from_parts(
        str(arguments.date),
        str(arguments.cycle),
    )

    project_root = Path.cwd().resolve()

    config_path = Path(str(arguments.config))

    config = load_pipeline_config(config_path)

    dry_run = bool(arguments.dry_run)

    execute = bool(arguments.execute)

    resume = bool(arguments.resume)

    if dry_run == execute:
        raise ValueError("Choose exactly one of --dry-run or --execute.")

    if resume and not execute:
        raise ValueError("--resume applies only to --execute.")

    if execute and config.execution_mode != "test":
        raise ValueError(
            "Execution is permitted only for pipelines whose execution_mode is 'test'."
        )

    stages = build_plan(
        config,
        run_id,
        project_root,
    )

    state_root = Path(str(arguments.state_root))

    state_path = state_root / run_id.value / "run_status.json"

    print(f"Run ID: {run_id.value}")

    print(f"Pipeline: {config.name}")

    print(f"Execution mode: {config.execution_mode}")

    print(f"Stages: {len(stages)}")

    print()

    _print_plan(stages)

    print()

    if dry_run:
        write_plan_state(
            state_path,
            run_id=run_id,
            pipeline_name=config.name,
            config_path=config_path,
            project_root=project_root,
            stages=stages,
            overwrite=bool(arguments.overwrite_state),
        )

        print(f"State file: {state_path}")

        print("DRY RUN: no pipeline stage was executed.")

        return 0

    resuming = resume and state_path.is_file()

    if resuming:
        print("Resuming existing run state; SUCCEEDED stages are not rerun.")
    else:
        write_execution_state(
            state_path,
            run_id=run_id,
            pipeline_name=config.name,
            config_path=config_path,
            project_root=project_root,
            stages=stages,
            overwrite=bool(arguments.overwrite_state),
        )

    print("Executing test pipeline...")

    return_code = execute_plan(
        state_path=state_path,
        stages=stages,
        project_root=project_root,
        resume=resuming,
    )

    print(f"State file: {state_path}")

    print(f"Test pipeline return code: {return_code}")

    return return_code


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

    run_parser = subparsers.add_parser(
        "run",
        help=("Plan a production cycle or execute an explicitly marked test pipeline."),
    )

    run_parser.add_argument(
        "--date",
        required=True,
        help="Initialization date as YYYYMMDD.",
    )

    run_parser.add_argument(
        "--cycle",
        default="00",
        help=("Initialization cycle: 00, 06, 12, or 18."),
    )

    run_parser.add_argument(
        "--config",
        default="configs/pipeline.json",
        help="Pipeline configuration path.",
    )

    run_parser.add_argument(
        "--state-root",
        default="archive/runs",
        help=("Directory under which run state directories are created."),
    )

    mode_group = run_parser.add_mutually_exclusive_group(required=True)

    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help=("Create and display the execution plan without running stages."),
    )

    mode_group.add_argument(
        "--execute",
        action="store_true",
        help=("Execute a configuration explicitly marked as a test pipeline."),
    )

    run_parser.add_argument(
        "--resume",
        action="store_true",
        help=("Reuse an existing run state: keep SUCCEEDED stages and retry the rest."),
    )

    run_parser.add_argument(
        "--overwrite-state",
        "--overwrite-plan",
        dest="overwrite_state",
        action="store_true",
        help=("Replace an existing state file."),
    )

    run_parser.set_defaults(
        handler=_run_pipeline,
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
    except (
        FileExistsError,
        FileNotFoundError,
        ValueError,
    ) as error:
        parser.error(str(error))
        return 2

    if not isinstance(result, int):
        raise TypeError("CLI command handler must return an integer.")

    return result
