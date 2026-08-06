"""Tests for the harmless sequential executor."""

from __future__ import annotations

import sys
from pathlib import Path

from gtf.orchestration.executor import (
    execute_plan,
)
from gtf.orchestration.planner import (
    PlannedStage,
)
from gtf.orchestration.state import (
    read_run_state,
    write_execution_state,
)
from gtf.run_id import RunId

ROOT = Path(__file__).resolve().parents[1]

FIXTURE_SCRIPT = "tests/fixtures/stages/controlled_stage.py"


def stage(
    name: str,
    *,
    exit_code: int = 0,
    required: bool = True,
) -> PlannedStage:
    """Construct a harmless fixture stage."""

    return PlannedStage(
        name=name,
        category="test",
        script=FIXTURE_SCRIPT,
        required=required,
        command=(
            sys.executable,
            FIXTURE_SCRIPT,
            "--message",
            name,
            "--exit-code",
            str(exit_code),
        ),
    )


def create_state(
    path: Path,
    stages: tuple[PlannedStage, ...],
) -> None:
    """Create executable state for a fixture plan."""

    write_execution_state(
        path,
        run_id=RunId.parse("20260730_00z"),
        pipeline_name="executor-test",
        config_path=Path(__file__),
        project_root=ROOT,
        stages=stages,
    )


def test_successful_execution(
    tmp_path: Path,
) -> None:
    stages = (
        stage("first"),
        stage("second"),
    )

    state_path = tmp_path / "run_status.json"

    create_state(
        state_path,
        stages,
    )

    return_code = execute_plan(
        state_path=state_path,
        stages=stages,
        project_root=ROOT,
    )

    payload = read_run_state(state_path)

    assert return_code == 0
    assert payload["status"] == "SUCCEEDED"
    assert payload["return_code"] == 0

    assert [item["status"] for item in payload["stages"]] == [
        "SUCCEEDED",
        "SUCCEEDED",
    ]

    for item in payload["stages"]:
        log_path = Path(item["log_path"])

        assert log_path.is_file()
        assert item["name"] in (log_path.read_text(encoding="utf-8"))


def test_required_failure_stops_pipeline(
    tmp_path: Path,
) -> None:
    stages = (
        stage("before_failure"),
        stage(
            "required_failure",
            exit_code=7,
        ),
        stage("must_not_execute"),
    )

    state_path = tmp_path / "run_status.json"

    create_state(
        state_path,
        stages,
    )

    return_code = execute_plan(
        state_path=state_path,
        stages=stages,
        project_root=ROOT,
    )

    payload = read_run_state(state_path)

    assert return_code == 7
    assert payload["status"] == "FAILED"
    assert payload["return_code"] == 7

    assert [item["status"] for item in payload["stages"]] == [
        "SUCCEEDED",
        "FAILED",
        "SKIPPED",
    ]

    skipped_stage = payload["stages"][2]

    assert skipped_stage["log_path"] is None
