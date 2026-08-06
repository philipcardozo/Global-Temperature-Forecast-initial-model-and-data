"""Pipeline configuration loading and validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

ExecutionMode = Literal[
    "production",
    "test",
]

_PLACEHOLDER_PATTERN = re.compile(r"\{[^{}]+\}")

_ALLOWED_PLACEHOLDERS = {
    "{cycle}",
    "{date}",
    "{run_id}",
}


@dataclass(frozen=True, slots=True)
class StageConfig:
    """Configuration for one pipeline stage."""

    name: str
    category: str
    script: str
    enabled: bool
    required: bool
    arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Validated forecast pipeline configuration."""

    schema_version: int
    name: str
    execution_mode: ExecutionMode
    stages: tuple[StageConfig, ...]


def _require_mapping(
    value: object,
    label: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")

    return cast(
        dict[str, object],
        value,
    )


def _require_string(
    value: object,
    label: str,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")

    normalized = value.strip()

    if not normalized:
        raise ValueError(f"{label} must not be empty.")

    return normalized


def _require_bool(
    value: object,
    label: str,
) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean.")

    return value


def _require_integer(
    value: object,
    label: str,
) -> int:
    if isinstance(value, bool) or not isinstance(
        value,
        int,
    ):
        raise ValueError(f"{label} must be an integer.")

    return value


def _require_execution_mode(
    value: object,
    label: str,
) -> ExecutionMode:
    normalized = _require_string(
        value,
        label,
    )

    if normalized not in {
        "production",
        "test",
    }:
        raise ValueError(f"{label} must be either 'production' or 'test'.")

    return cast(
        ExecutionMode,
        normalized,
    )


def _require_arguments(
    value: object,
    label: str,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a JSON array.")

    arguments: list[str] = []

    for index, item in enumerate(value):
        argument = _require_string(
            item,
            f"{label}[{index}]",
        )

        placeholders = set(_PLACEHOLDER_PATTERN.findall(argument))

        unsupported = placeholders - _ALLOWED_PLACEHOLDERS

        if unsupported:
            raise ValueError(
                f"{label}[{index}] contains "
                "unsupported placeholders: "
                f"{sorted(unsupported)}"
            )

        arguments.append(argument)

    return tuple(arguments)


def load_pipeline_config(
    path: Path,
) -> PipelineConfig:
    """Load and validate a pipeline JSON file."""

    raw_value: object = json.loads(
        path.read_text(
            encoding="utf-8",
        )
    )

    raw = _require_mapping(
        raw_value,
        "pipeline",
    )

    schema_version = _require_integer(
        raw.get("schema_version"),
        "pipeline.schema_version",
    )

    if schema_version != 1:
        raise ValueError("Only pipeline schema version 1 is supported.")

    name = _require_string(
        raw.get("name"),
        "pipeline.name",
    )

    execution_mode = _require_execution_mode(
        raw.get("execution_mode"),
        "pipeline.execution_mode",
    )

    stages_value = raw.get("stages")

    if not isinstance(stages_value, list):
        raise ValueError("pipeline.stages must be a JSON array.")

    stages: list[StageConfig] = []
    seen_names: set[str] = set()

    for index, stage_value in enumerate(stages_value):
        label = f"pipeline.stages[{index}]"

        stage = _require_mapping(
            stage_value,
            label,
        )

        stage_name = _require_string(
            stage.get("name"),
            f"{label}.name",
        )

        if stage_name in seen_names:
            raise ValueError(f"Pipeline stage names must be unique: {stage_name}")

        seen_names.add(stage_name)

        stages.append(
            StageConfig(
                name=stage_name,
                category=_require_string(
                    stage.get("category"),
                    f"{label}.category",
                ),
                script=_require_string(
                    stage.get("script"),
                    f"{label}.script",
                ),
                enabled=_require_bool(
                    stage.get("enabled"),
                    f"{label}.enabled",
                ),
                required=_require_bool(
                    stage.get("required"),
                    f"{label}.required",
                ),
                arguments=_require_arguments(
                    stage.get("arguments"),
                    f"{label}.arguments",
                ),
            )
        )

    if not stages:
        raise ValueError("Pipeline must contain at least one stage.")

    return PipelineConfig(
        schema_version=schema_version,
        name=name,
        execution_mode=execution_mode,
        stages=tuple(stages),
    )
