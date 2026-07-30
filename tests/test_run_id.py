"""Tests for forecast run identifiers."""

from datetime import UTC, datetime

import pytest

from gtf.run_id import RunId


def test_parse_run_id() -> None:
    run_id = RunId.parse("20260728_00z")

    assert run_id.value == "20260728_00z"
    assert run_id.date_text == "20260728"
    assert run_id.cycle_text == "00"
    assert run_id.cycle == 0


def test_initialization_utc() -> None:
    run_id = RunId.parse("20260728_18z")

    assert run_id.initialization_utc == datetime(
        2026,
        7,
        28,
        18,
        tzinfo=UTC,
    )


def test_from_parts_normalizes_cycle() -> None:
    run_id = RunId.from_parts(
        "20260728",
        "6",
    )

    assert run_id.value == "20260728_06z"


@pytest.mark.parametrize(
    "value",
    [
        "20260728",
        "20260728_01z",
        "2026-07-28_00z",
        "20260728_00",
        "not-a-run",
    ],
)
def test_rejects_invalid_format(
    value: str,
) -> None:
    with pytest.raises(ValueError):
        RunId.parse(value)


def test_rejects_invalid_calendar_date() -> None:
    with pytest.raises(
        ValueError,
        match="invalid date",
    ):
        RunId.parse("20260230_00z")
