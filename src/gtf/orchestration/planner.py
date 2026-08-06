"""Build deterministic forecast-cycle execution plans."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from gtf.orchestration.config import (
    PipelineConfig,
)
from gtf.run_id import RunId


@dataclass(frozen=True, slots=True)
class PlannedStage:
    """One rendered pipeline stage."""

    name: str
    category: str
    script: str
    required: bool
    command: tuple[str, ...]


def build_plan(
    config: PipelineConfig,
    run_id: RunId,
    project_root: Path,
) -> tuple[PlannedStage, ...]:
    """Render enabled stages for one forecast run."""

    values = {
        "date": run_id.date_text,
        "cycle": run_id.cycle_text,
        "run_id": run_id.value,
    }

    stages: list[PlannedStage] = []

    for stage in config.stages:
        if not stage.enabled:
            continue

        script_path = project_root / stage.script

        if not script_path.is_file():
            raise FileNotFoundError(
                f"Pipeline stage script does not exist: {script_path}"
            )

        arguments = tuple(argument.format_map(values) for argument in stage.arguments)

        stages.append(
            PlannedStage(
                name=stage.name,
                category=stage.category,
                script=stage.script,
                required=stage.required,
                command=(
                    sys.executable,
                    stage.script,
                    *arguments,
                ),
            )
        )

    if not stages:
        raise ValueError("Pipeline contains no enabled stages.")

    return tuple(stages)
