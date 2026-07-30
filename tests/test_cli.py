"""Tests for the initial command-line interface."""

from _pytest.capture import CaptureFixture

from gtf.cli import main


def test_cli_without_command_prints_help(
    capsys: CaptureFixture[str],
) -> None:
    result = main([])

    assert result == 0

    output = capsys.readouterr().out

    assert "Global Temperature Forecast" in output
    assert "validate-run-id" in output
    assert "audit" in output


def test_validate_run_id_command(
    capsys: CaptureFixture[str],
) -> None:
    result = main(
        [
            "validate-run-id",
            "20260728_00z",
        ]
    )

    assert result == 0

    output = capsys.readouterr().out

    assert "20260728_00z" in output
    assert "2026-07-28T00:00:00+00:00" in output
