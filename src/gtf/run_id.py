"""Forecast run identifier parsing and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date as Date

_RUN_ID_PATTERN = re.compile(r"^(?P<date>[0-9]{8})_(?P<cycle>00|06|12|18)z$")


@dataclass(frozen=True, slots=True)
class RunId:
    """A validated forecast initialization identifier."""

    date: Date
    cycle: int

    def __post_init__(self) -> None:
        if self.cycle not in {0, 6, 12, 18}:
            raise ValueError("Forecast cycle must be one of 00, 06, 12, or 18.")

    @property
    def value(self) -> str:
        """Return the canonical run identifier."""

        return f"{self.date:%Y%m%d}_{self.cycle:02d}z"

    @property
    def date_text(self) -> str:
        """Return the initialization date as YYYYMMDD."""

        return f"{self.date:%Y%m%d}"

    @property
    def cycle_text(self) -> str:
        """Return the initialization cycle as two digits."""

        return f"{self.cycle:02d}"

    @property
    def initialization_utc(self) -> datetime:
        """Return the initialization as a timezone-aware UTC datetime."""

        return datetime(
            year=self.date.year,
            month=self.date.month,
            day=self.date.day,
            hour=self.cycle,
            tzinfo=UTC,
        )

    @classmethod
    def parse(cls, value: str) -> RunId:
        """Parse a canonical YYYYMMDD_CCz run identifier."""

        match = _RUN_ID_PATTERN.fullmatch(value.strip())

        if match is None:
            raise ValueError(
                "Run ID must use YYYYMMDD_CCz, where CC is 00, 06, 12, or 18."
            )

        try:
            parsed_date = datetime.strptime(
                match.group("date"),
                "%Y%m%d",
            ).date()
        except ValueError as error:
            raise ValueError(f"Run ID contains an invalid date: {value}") from error

        return cls(
            date=parsed_date,
            cycle=int(match.group("cycle")),
        )

    @classmethod
    def from_parts(
        cls,
        date_text: str,
        cycle_text: str,
    ) -> RunId:
        """Build a run identifier from separate date and cycle values."""

        normalized_cycle = cycle_text.strip()

        if normalized_cycle.isdigit():
            normalized_cycle = f"{int(normalized_cycle):02d}"

        return cls.parse(f"{date_text.strip()}_{normalized_cycle}z")
