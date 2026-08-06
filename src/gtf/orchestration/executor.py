"""Sequential pipeline-stage execution."""

from __future__ import annotations

import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from gtf.orchestration.planner import PlannedStage
from gtf.orchestration.state import (
    read_run_state,
    write_run_state,
)


def _utc_now() -> str:
    """Return the current UTC time in ISO-8601 format."""

    return datetime.now(UTC).isoformat()


def _stage_records(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate and return mutable stage records."""

    value = payload.get("stages")

    if not isinstance(value, list):
        raise ValueError("Run state stages must be a JSON array.")

    records: list[dict[str, Any]] = []

    for position, item in enumerate(
        value,
        start=1,
    ):
        if not isinstance(item, dict):
            raise ValueError(f"Run state stage {position} must be an object.")

        records.append(cast(dict[str, Any], item))

    return records


def _skip_remaining_stages(
    records: list[dict[str, Any]],
    *,
    after_index: int,
    reason: str,
) -> None:
    """Mark all unstarted stages after a failure as skipped."""

    timestamp = _utc_now()

    for record in records[after_index + 1 :]:
        if record["status"] != "PENDING":
            continue

        record["status"] = "SKIPPED"
        record["completed_utc"] = timestamp
        record["error"] = reason


def execute_plan(
    *,
    state_path: Path,
    stages: tuple[PlannedStage, ...],
    project_root: Path,
) -> int:
    """Execute stages sequentially and persist every transition."""

    payload = read_run_state(state_path)

    if payload.get("dry_run") is not False:
        raise ValueError("A dry-run state cannot be executed.")

    if payload.get("status") != "PLANNED":
        raise ValueError("Execution requires a PLANNED state.")

    records = _stage_records(payload)

    if len(records) != len(stages):
        raise ValueError("State stage count does not match the execution plan.")

    logs_directory = state_path.parent / "logs"

    logs_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload["status"] = "RUNNING"
    payload["started_utc"] = _utc_now()

    write_run_state(
        state_path,
        payload,
    )

    optional_failure = False

    for index, (stage, record) in enumerate(
        zip(
            stages,
            records,
            strict=True,
        )
    ):
        started_utc = _utc_now()

        log_path = logs_directory / (f"{index + 1:02d}_{stage.name}.log")

        record["status"] = "RUNNING"
        record["started_utc"] = started_utc
        record["log_path"] = str(log_path.resolve())

        write_run_state(
            state_path,
            payload,
        )

        return_code = 1
        error_message: str | None = None

        try:
            with log_path.open(
                "w",
                encoding="utf-8",
            ) as log:
                log.write("$ " + shlex.join(stage.command) + "\n\n")
                log.flush()

                result = subprocess.run(
                    stage.command,
                    cwd=project_root,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )

                return_code = result.returncode

        except OSError as error:
            error_message = f"{type(error).__name__}: {error}"

            log_path.write_text(
                error_message + "\n",
                encoding="utf-8",
            )

        record["completed_utc"] = _utc_now()
        record["return_code"] = return_code

        if return_code == 0:
            record["status"] = "SUCCEEDED"
            record["error"] = None

            write_run_state(
                state_path,
                payload,
            )

            continue

        record["status"] = "FAILED"
        record["error"] = error_message or (
            f"Stage exited with return code {return_code}."
        )

        if stage.required:
            reason = f"Skipped after required stage {stage.name} failed."

            _skip_remaining_stages(
                records,
                after_index=index,
                reason=reason,
            )

            payload["status"] = "FAILED"
            payload["completed_utc"] = _utc_now()
            payload["return_code"] = return_code

            write_run_state(
                state_path,
                payload,
            )

            return return_code if return_code != 0 else 1

        optional_failure = True

        write_run_state(
            state_path,
            payload,
        )

    payload["status"] = "COMPLETED_WITH_ERRORS" if optional_failure else "SUCCEEDED"

    payload["completed_utc"] = _utc_now()
    payload["return_code"] = 0

    write_run_state(
        state_path,
        payload,
    )

    return 0
