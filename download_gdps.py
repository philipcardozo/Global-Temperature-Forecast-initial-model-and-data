from __future__ import annotations

import argparse
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests


BASE_HOST = "https://dd.weather.gc.ca"

HEADERS = {
    "User-Agent": (
        "Global-Temperature-Model/1.0 "
        "(research data downloader)"
    )
}


def validate_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Date must use YYYYMMDD format."
        ) from error

    return value


def filename(
    date: str,
    cycle: str,
    forecast_hour: int,
) -> str:
    return (
        f"{date}T{cycle}Z_MSC_GDPS_"
        f"AirTemp_AGL-2m_"
        f"LatLon0.15_"
        f"PT{forecast_hour:03d}H.grib2"
    )


def candidate_directories(
    date: str,
    cycle: str,
    forecast_hour: int,
) -> list[str]:
    hour = f"{forecast_hour:03d}"

    # The dated archive is the reproducible source.
    archive = (
        f"{BASE_HOST}/{date}/WXO-DD/"
        f"model_gdps/15km/{cycle}/{hour}/"
    )

    candidates = [archive]

    # The "today" path may publish the newest run sooner.
    today_utc = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d")

    if date == today_utc:
        current = (
            f"{BASE_HOST}/today/"
            f"model_gdps/15km/"
            f"{cycle}/{hour}/"
        )

        candidates.insert(0, current)

    return candidates


def candidate_urls(
    date: str,
    cycle: str,
    forecast_hour: int,
) -> list[str]:
    name = filename(
        date,
        cycle,
        forecast_hour,
    )

    return [
        urljoin(directory, name)
        for directory in candidate_directories(
            date,
            cycle,
            forecast_hour,
        )
    ]


def grib_message_count(path: Path) -> int:
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


def valid_grib(path: Path) -> bool:
    try:
        # Each GDPS file requested here should contain
        # one global 2-meter-temperature field.
        return grib_message_count(path) == 1
    except (
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ):
        return False


def destination_path(
    date: str,
    cycle: str,
    forecast_hour: int,
) -> Path:
    directory = (
        Path("data/gdps")
        / f"{date}_{cycle}z"
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return directory / (
        f"gdps_{date}_{cycle}z_"
        f"f{forecast_hour:03d}.grib2"
    )


def download_one(
    session: requests.Session,
    date: str,
    cycle: str,
    forecast_hour: int,
    attempts: int = 4,
) -> tuple[str, str]:
    destination = destination_path(
        date,
        cycle,
        forecast_hour,
    )

    label = f"f{forecast_hour:03d}"

    if valid_grib(destination):
        return "skipped", label

    temporary = destination.with_suffix(
        ".grib2.part"
    )

    last_error = "No candidate URL succeeded."

    for url in candidate_urls(
        date,
        cycle,
        forecast_hour,
    ):
        for attempt in range(1, attempts + 1):
            temporary.unlink(missing_ok=True)

            try:
                with session.get(
                    url,
                    stream=True,
                    timeout=(30, 240),
                ) as response:
                    if response.status_code == 404:
                        last_error = (
                            f"Not found: {url}"
                        )
                        break

                    response.raise_for_status()

                    chunks = response.iter_content(
                        chunk_size=1024 * 1024
                    )

                    first_chunk = next(
                        chunks,
                        b"",
                    )

                    if not first_chunk.startswith(b"GRIB"):
                        preview = first_chunk[:150].decode(
                            "utf-8",
                            errors="replace",
                        )

                        raise RuntimeError(
                            "Response was not GRIB data: "
                            f"{preview!r}"
                        )

                    with temporary.open("wb") as output:
                        output.write(first_chunk)

                        for chunk in chunks:
                            if chunk:
                                output.write(chunk)

                if not valid_grib(temporary):
                    raise RuntimeError(
                        "Downloaded file failed GRIB "
                        "message validation."
                    )

                temporary.replace(destination)

                size_mb = (
                    destination.stat().st_size
                    / 1_000_000
                )

                return (
                    "downloaded",
                    f"{label} ({size_mb:.2f} MB)",
                )

            except (
                requests.RequestException,
                RuntimeError,
            ) as error:
                last_error = str(error)
                temporary.unlink(missing_ok=True)

                if attempt < attempts:
                    time.sleep(
                        min(20, 2 ** attempt)
                    )

    return "failed", f"{label}: {last_error}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download Canadian GDPS global "
            "2-meter-temperature GRIB2 files."
        )
    )

    parser.add_argument(
        "--date",
        required=True,
        type=validate_date,
    )

    parser.add_argument(
        "--cycle",
        default="00",
        choices=("00", "12"),
    )

    parser.add_argument(
        "--max-hour",
        type=int,
        default=240,
    )

    parser.add_argument(
        "--step",
        type=int,
        default=6,
    )

    parser.add_argument(
        "--pause",
        type=float,
        default=0.25,
    )

    args = parser.parse_args()

    if args.max_hour < 0:
        raise SystemExit(
            "--max-hour must be nonnegative."
        )

    if args.step <= 0:
        raise SystemExit(
            "--step must be positive."
        )

    forecast_hours = list(
        range(
            0,
            args.max_hour + 1,
            args.step,
        )
    )

    print(
        f"GDPS initialization: "
        f"{args.date} {args.cycle}Z"
    )
    print(
        f"Forecast fields requested: "
        f"{len(forecast_hours)}"
    )

    session = requests.Session()
    session.headers.update(HEADERS)

    downloaded = 0
    skipped = 0
    failures: list[str] = []

    for forecast_hour in forecast_hours:
        status, message = download_one(
            session,
            args.date,
            args.cycle,
            forecast_hour,
        )

        print(
            f"[{status.upper():10}] {message}",
            flush=True,
        )

        if status == "downloaded":
            downloaded += 1
        elif status == "skipped":
            skipped += 1
        else:
            failures.append(message)

        time.sleep(args.pause)

    run_directory = (
        Path("data/gdps")
        / f"{args.date}_{args.cycle}z"
    )

    failure_path = (
        run_directory
        / "failed_downloads.txt"
    )

    if failures:
        failure_path.write_text(
            "\n".join(failures) + "\n",
            encoding="utf-8",
        )
    else:
        failure_path.unlink(
            missing_ok=True
        )

    print("\nDownload summary")
    print(f"Downloaded: {downloaded}")
    print(f"Skipped:    {skipped}")
    print(f"Failed:     {len(failures)}")

    if failures:
        print(
            f"Failures recorded in {failure_path}"
        )
        raise SystemExit(2)


if __name__ == "__main__":
    main()
