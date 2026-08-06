"""Tests for forecast-cycle planning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _pytest.capture import CaptureFixture
from _pytest.tmpdir import TempPathFactory

from gtf.cli import main
from gtf.orchestration.config import (
    load_pipeline_config,
)
from gtf.orchestration.planner import (
    build_plan,
)
from gtf.orchestration.state import (
    write_plan_state,
)
from gtf.run_id import RunId

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "pipeline.json"
TEST_CONFIG_PATH = ROOT / "tests" / "fixtures" / "pipelines" / "test_pipeline.json"


def test_pipeline_configuration() -> None:
    config = load_pipeline_config(CONFIG_PATH)

    assert config.schema_version == 1
    assert config.name == ("daily-global-temperature-forecast")
    assert len(config.stages) == 17
    assert all(stage.enabled for stage in config.stages)


def test_plan_renders_run_arguments() -> None:
    config = load_pipeline_config(CONFIG_PATH)

    run_id = RunId.parse("20260730_00z")

    plan = build_plan(
        config,
        run_id,
        ROOT,
    )

    assert len(plan) == 17
    assert plan[0].name == "download_gfs"
    assert "--date" in plan[0].command
    assert "20260730" in plan[0].command
    assert "--cycle" in plan[0].command
    assert "00" in plan[0].command

    snapshot = next(stage for stage in plan if stage.name == "snapshot_run")

    assert "--init-date" in snapshot.command
    assert "20260730" in snapshot.command


def test_state_file_creation(
    tmp_path_factory: TempPathFactory,
) -> None:
    temporary_root = tmp_path_factory.mktemp("state")

    config = load_pipeline_config(CONFIG_PATH)

    run_id = RunId.parse("20260730_00z")

    plan = build_plan(
        config,
        run_id,
        ROOT,
    )

    state_path = temporary_root / run_id.value / "run_status.json"

    write_plan_state(
        state_path,
        run_id=run_id,
        pipeline_name=config.name,
        config_path=CONFIG_PATH,
        project_root=ROOT,
        stages=plan,
    )

    payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert payload["status"] == "PLANNED"
    assert payload["dry_run"] is True
    assert payload["run_id"] == run_id.value
    assert len(payload["stages"]) == 17
    assert all(stage["status"] == "PENDING" for stage in payload["stages"])


def test_cli_dry_run(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    result = main(
        [
            "run",
            "--date",
            "20260730",
            "--cycle",
            "00",
            "--dry-run",
            "--state-root",
            str(tmp_path),
        ]
    )

    assert result == 0

    output = capsys.readouterr().out

    assert "Run ID: 20260730_00z" in output
    assert "Stages: 17" in output
    assert "no pipeline stage was executed" in output

    state_path = tmp_path / "20260730_00z" / "run_status.json"

    assert state_path.is_file()


def test_cli_rejects_production_execution(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        SystemExit,
    ) as error:
        main(
            [
                "run",
                "--date",
                "20260730",
                "--cycle",
                "00",
                "--execute",
                "--state-root",
                str(tmp_path),
            ]
        )

    assert error.value.code == 2


def test_cli_executes_test_pipeline(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    result = main(
        [
            "run",
            "--date",
            "20260730",
            "--cycle",
            "00",
            "--execute",
            "--config",
            str(TEST_CONFIG_PATH),
            "--state-root",
            str(tmp_path),
        ]
    )

    assert result == 0

    output = capsys.readouterr().out

    assert "Execution mode: test" in output
    assert "Executing test pipeline" in output

    state_path = tmp_path / "20260730_00z" / "run_status.json"

    payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert payload["status"] == "COMPLETED_WITH_ERRORS"

    assert [stage["status"] for stage in payload["stages"]] == [
        "SUCCEEDED",
        "FAILED",
        "SUCCEEDED",
    ]

    assert all(stage["log_path"] is not None for stage in payload["stages"])
