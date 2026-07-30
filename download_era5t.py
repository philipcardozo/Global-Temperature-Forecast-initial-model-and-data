from __future__ import annotations

import argparse
import subprocess
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import cdsapi


DATASET = "reanalysis-era5-single-levels"

HOURS = [
    f"{hour:02d}:00"
    for hour in range(24)
]


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(
            value,
            "%Y%m%d",
        ).date()
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Date must use YYYYMMDD format."
        ) from error


def date_range(
    start_date: date,
    end_date: date,
):
    current = start_date

    while current <= end_date:
        yield current
        current += timedelta(days=1)


def grib_message_count(path: Path) -> int:
    """Return the number of GRIB messages in a file."""

    if not path.exists() or path.stat().st_size < 8:
        return 0

    with path.open("rb") as file:
        if file.read(4) != b"GRIB":
            return 0

    result = subprocess.run(
        ["grib_count", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )

    return int(result.stdout.strip())


def valid_grib(
    path: Path,
    expected_messages: int = 24,
) -> bool:
    """
    A complete ERA5T daily file must contain exactly
    24 hourly GRIB messages.
    """

    try:
        return (
            grib_message_count(path)
            == expected_messages
        )
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ):
        return False


def normalize_download(
    downloaded_path: Path,
    final_path: Path,
) -> None:
    """
    CDS may return either a direct GRIB file or a ZIP
    containing one or more GRIB files.
    """

    with downloaded_path.open("rb") as file:
        signature = file.read(4)

    if signature == b"GRIB":
        downloaded_path.replace(final_path)
        return

    if signature[:2] != b"PK":
        raise RuntimeError(
            "CDS response was neither GRIB nor ZIP."
        )

    with zipfile.ZipFile(downloaded_path) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if not name.endswith("/")
        )

        grib_contents: list[bytes] = []

        for name in names:
            content = archive.read(name)

            if content.startswith(b"GRIB"):
                grib_contents.append(content)

        if not grib_contents:
            raise RuntimeError(
                "ZIP archive contained no GRIB data."
            )

        with final_path.open("wb") as output:
            for content in grib_contents:
                output.write(content)

    downloaded_path.unlink(missing_ok=True)


def download_day(
    client: cdsapi.Client,
    requested_date: date,
) -> Path:
    date_string = requested_date.strftime("%Y%m%d")

    directory = (
        Path("data/era5t")
        / date_string
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    final_path = (
        directory
        / f"era5t_{date_string}_t2m_hourly.grib"
    )

    temporary_path = (
        directory
        / f"era5t_{date_string}_download.tmp"
    )

    if valid_grib(final_path):
        print(f"Already exists: {final_path}")
        return final_path

    temporary_path.unlink(missing_ok=True)
    final_path.unlink(missing_ok=True)

    request = {
        "product_type": ["reanalysis"],
        "variable": ["2m_temperature"],
        "date": date_string,
        "time": HOURS,

        # Full Earth: north, west, south, east.
        "area": [90, -180, -90, 180],

        # ERA5 atmospheric grid resolution.
        "grid": [0.25, 0.25],

        "data_format": "grib",
    }

    print(
        f"Requesting ERA5T {date_string}: "
        "24 hourly global temperature fields"
    )

    try:
        client.retrieve(
            DATASET,
            request,
            str(temporary_path),
        )

        normalize_download(
            temporary_path,
            final_path,
        )

        if not valid_grib(final_path):
            raise RuntimeError(
                "Final file failed GRIB validation."
            )

    except Exception:
        temporary_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise

    size_mb = final_path.stat().st_size / 1_000_000

    print(
        f"Saved: {final_path} "
        f"({size_mb:.1f} MB)"
    )

    return final_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download global ERA5T hourly "
            "2-meter temperature."
        )
    )

    parser.add_argument(
        "--date",
        type=parse_date,
        help="One date in YYYYMMDD format.",
    )

    parser.add_argument(
        "--start-date",
        type=parse_date,
    )

    parser.add_argument(
        "--end-date",
        type=parse_date,
    )

    args = parser.parse_args()

    if args.date is not None:
        dates = [args.date]

    elif (
        args.start_date is not None
        and args.end_date is not None
    ):
        if args.end_date < args.start_date:
            raise SystemExit(
                "End date cannot precede start date."
            )

        dates = list(
            date_range(
                args.start_date,
                args.end_date,
            )
        )

    else:
        raise SystemExit(
            "Use --date, or use both "
            "--start-date and --end-date."
        )

    client = cdsapi.Client()
    failures: list[str] = []

    for requested_date in dates:
        try:
            download_day(
                client,
                requested_date,
            )
        except Exception as error:
            message = (
                f"{requested_date}: "
                f"{type(error).__name__}: {error}"
            )

            failures.append(message)
            print(f"FAILED: {message}")

    if failures:
        failure_path = (
            Path("data/era5t")
            / "failed_downloads.txt"
        )

        failure_path.write_text(
            "\n".join(failures) + "\n",
            encoding="utf-8",
        )

        print(
            f"\nFailures recorded in "
            f"{failure_path}"
        )

        raise SystemExit(2)


if __name__ == "__main__":
    main()
