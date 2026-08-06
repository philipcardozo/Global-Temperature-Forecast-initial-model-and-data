"""Atomic pipeline state-file management."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gtf.orchestration.planner import PlannedStage
from gtf.run_id import RunId


def _utc_now() -> str:
    """Return the current UTC time in ISO-8601 format."""

    return datetime.now(UTC).isoformat()


def _atomic_write(
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Atomically replace a JSON state file."""

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")

    try:
        temporary_path.write_text(
            json.dumps(
                payload,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        os.replace(
            temporary_path,
            path,
        )
    finally:
        temporary_path.unlink(missing_ok=True)


def read_run_state(
    path: Path,
) -> dict[str, Any]:
    """Load a run-state JSON document."""

    payload: object = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise ValueError("Run state must contain a JSON object.")

    return payload


def write_run_state(
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Atomically persist an existing run state."""

    payload["updated_utc"] = _utc_now()

    _atomic_write(
        path,
        payload,
    )


def _write_initial_state(
    path: Path,
    *,
    run_id: RunId,
    pipeline_name: str,
    config_path: Path,
    project_root: Path,
    stages: tuple[PlannedStage, ...],
    dry_run: bool,
    overwrite: bool,
) -> Path:
    """Create an initial pipeline state document."""

    if path.exists() and not overwrite:
        raise FileExistsError(
            f"State file already exists: {path}. Use --overwrite-plan to replace it."
        )

    created_utc = _utc_now()

    payload: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id.value,
        "initialization_utc": (run_id.initialization_utc.isoformat()),
        "pipeline": pipeline_name,
        "status": "PLANNED",
        "dry_run": dry_run,
        "created_utc": created_utc,
        "updated_utc": created_utc,
        "started_utc": None,
        "completed_utc": None,
        "return_code": None,
        "project_root": str(project_root.resolve()),
        "config_path": str(config_path.resolve()),
        "stages": [
            {
                "position": position,
                "name": stage.name,
                "category": stage.category,
                "script": stage.script,
                "required": stage.required,
                "status": "PENDING",
                "command": list(stage.command),
                "log_path": None,
                "started_utc": None,
                "completed_utc": None,
                "return_code": None,
                "error": None,
            }
            for position, stage in enumerate(
                stages,
                start=1,
            )
        ],
    }

    _atomic_write(
        path,
        payload,
    )

    return path


def write_plan_state(
    path: Path,
    *,
    run_id: RunId,
    pipeline_name: str,
    config_path: Path,
    project_root: Path,
    stages: tuple[PlannedStage, ...],
    overwrite: bool = False,
) -> Path:
    """Write an atomic dry-run state file."""

    return _write_initial_state(
        path,
        run_id=run_id,
        pipeline_name=pipeline_name,
        config_path=config_path,
        project_root=project_root,
        stages=stages,
        dry_run=True,
        overwrite=overwrite,
    )


def write_execution_state(
    path: Path,
    *,
    run_id: RunId,
    pipeline_name: str,
    config_path: Path,
    project_root: Path,
    stages: tuple[PlannedStage, ...],
    overwrite: bool = False,
) -> Path:
    """Write initial state for an executable test pipeline."""

    return _write_initial_state(
        path,
        run_id=run_id,
        pipeline_name=pipeline_name,
        config_path=config_path,
        project_root=project_root,
        stages=stages,
        dry_run=False,
        overwrite=overwrite,
    )
