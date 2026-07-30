from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path

import requests


BASE_OUTPUT_DIRECTORY = Path("data/gfs")
DEFAULT_MAX_HOUR = 240
STEP_HOURS = 6

VALID_CYCLES = ("00", "06", "12", "18")
LATEST_FIRST_CYCLES = ("18", "12", "06", "00")


def valid_date(value: str) -> str:
    if not re.fullmatch(r"\d{8}", value):
        raise argparse.ArgumentTypeError(
            "Date must use YYYYMMDD format."
        )

    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"Invalid date: {value}"
        ) from error

    return value


def valid_max_hour(value: str) -> int:
    maximum = int(value)

    if maximum < 0 or maximum > 240:
        raise argparse.ArgumentTypeError(
            "--max-hour must be between 0 and 240."
        )

    if maximum % STEP_HOURS != 0:
        raise argparse.ArgumentTypeError(
            "--max-hour must be divisible by 6."
        )

    return maximum


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download run-scoped GFS 2-meter-temperature "
            "GRIB2 files."
        )
    )

    parser.add_argument(
        "--date",
        type=valid_date,
        default=datetime.now(
            timezone.utc
        ).strftime("%Y%m%d"),
        help="Initialization date in YYYYMMDD format.",
    )

    parser.add_argument(
        "--cycle",
        choices=VALID_CYCLES,
        default=None,
        help=(
            "Initialization cycle. When omitted, search "
            "for the latest available cycle."
        ),
    )

    parser.add_argument(
        "--max-hour",
        type=valid_max_hour,
        default=DEFAULT_MAX_HOUR,
        help="Maximum forecast hour; default: 240.",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing nonempty files.",
    )

    return parser.parse_args()


def build_url(
    date: str,
    cycle: str,
    forecast_hour: int,
) -> str:
    file_name = (
        f"gfs.t{cycle}z.pgrb2.0p25."
        f"f{forecast_hour:03d}"
    )

    parameters = {
        "file": file_name,
        "var_TMP": "on",
        "lev_2_m_above_ground": "on",
        "subregion": "",
        "leftlon": "0",
        "rightlon": "360",
        "toplat": "90",
        "bottomlat": "-90",
        "dir": f"/gfs.{date}/{cycle}/atmos",
    }

    request = requests.Request(
        "GET",
        (
            "https://nomads.ncep.noaa.gov/"
            "cgi-bin/filter_gfs_0p25.pl"
        ),
        params=parameters,
    )

    prepared = request.prepare()

    if prepared.url is None:
        raise RuntimeError(
            "Failed to construct the GFS download URL."
        )

    return prepared.url


def cycle_exists(
    date: str,
    cycle: str,
) -> bool:
    url = build_url(date, cycle, 0)

    try:
        response = requests.get(
            url,
            timeout=60,
        )

        return (
            response.status_code == 200
            and response.content.startswith(b"GRIB")
        )

    except requests.RequestException:
        return False


def find_latest_cycle(date: str) -> str:
    for cycle in LATEST_FIRST_CYCLES:
        print(
            f"Checking GFS {date} {cycle}Z..."
        )

        if cycle_exists(date, cycle):
            return cycle

    raise RuntimeError(
        f"No available GFS cycle found for {date}. "
        "Try the previous UTC date."
    )


def download_file(
    *,
    date: str,
    cycle: str,
    forecast_hour: int,
    output_directory: Path,
    overwrite: bool,
) -> Path | None:
    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = output_directory / (
        f"gfs_{date}_{cycle}z_"
        f"f{forecast_hour:03d}.grib2"
    )

    temporary = destination.with_suffix(
        destination.suffix + ".part"
    )

    if (
        destination.exists()
        and destination.stat().st_size > 0
        and not overwrite
    ):
        print(
            f"Already exists: {destination}"
        )
        return destination

    temporary.unlink(missing_ok=True)

    url = build_url(
        date,
        cycle,
        forecast_hour,
    )

    print(
        "Downloading forecast hour "
        f"{forecast_hour:03d}..."
    )

    try:
        with requests.get(
            url,
            stream=True,
            timeout=180,
        ) as response:
            response.raise_for_status()

            chunks = response.iter_content(
                chunk_size=1024 * 1024
            )

            first_chunk = next(chunks, b"")

            if not first_chunk.startswith(b"GRIB"):
                print(
                    "Not available: forecast hour "
                    f"{forecast_hour:03d}"
                )
                return None

            with temporary.open("wb") as stream:
                stream.write(first_chunk)

                for chunk in chunks:
                    if chunk:
                        stream.write(chunk)

    except requests.RequestException as error:
        print(
            "Failed forecast hour "
            f"{forecast_hour:03d}: {error}"
        )

        temporary.unlink(missing_ok=True)
        return None

    temporary.replace(destination)

    print(
        f"Saved {destination} "
        f"({destination.stat().st_size / 1_000_000:.2f} MB)"
    )

    return destination


def main() -> None:
    args = parse_args()

    cycle = (
        args.cycle
        if args.cycle is not None
        else find_latest_cycle(args.date)
    )

    run_id = f"{args.date}_{cycle}z"

    output_directory = (
        BASE_OUTPUT_DIRECTORY / run_id
    )

    forecast_hours = range(
        0,
        args.max_hour + 1,
        STEP_HOURS,
    )

    print(
        f"Using GFS initialization: "
        f"{args.date} {cycle}Z"
    )

    print(
        f"Output directory: "
        f"{output_directory}"
    )

    completed = 0

    for forecast_hour in forecast_hours:
        result = download_file(
            date=args.date,
            cycle=cycle,
            forecast_hour=forecast_hour,
            output_directory=output_directory,
            overwrite=args.overwrite,
        )

        if result is not None:
            completed += 1

    expected = (
        args.max_hour // STEP_HOURS
    ) + 1

    print()
    print(
        f"Available files: {completed}/{expected}"
    )

    if completed != expected:
        raise SystemExit(
            "GFS download is incomplete."
        )


if __name__ == "__main__":
    main()
