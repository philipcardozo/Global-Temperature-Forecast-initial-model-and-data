from __future__ import annotations

import argparse
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


BASE_HOST = "https://dd.weather.gc.ca"

HEADERS = {
    "User-Agent": (
        "Global-Temperature-Model/1.0 "
        "(scientific research)"
    )
}


def validate_date(value: str) -> str:
    if not re.fullmatch(r"\d{8}", value):
        raise argparse.ArgumentTypeError(
            "Date must use YYYYMMDD format."
        )

    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Invalid calendar date."
        ) from error

    return value


def remote_filename(
    date: str,
    cycle: str,
    forecast_hour: int,
) -> str:
    return (
        "CMC_geps-raw_TMP_TGL_2m_"
        "latlon0p5x0p5_"
        f"{date}{cycle}_"
        f"P{forecast_hour:03d}_"
        "allmbrs.grib2"
    )


def candidate_urls(
    date: str,
    cycle: str,
    forecast_hour: int,
) -> list[str]:
    hour = f"{forecast_hour:03d}"

    name = remote_filename(
        date,
        cycle,
        forecast_hour,
    )

    today_url = (
        f"{BASE_HOST}/today/"
        "ensemble/geps/grib2/raw/"
        f"{cycle}/{hour}/{name}"
    )

    archive_url = (
        f"{BASE_HOST}/{date}/WXO-DD/"
        "ensemble/geps/grib2/raw/"
        f"{cycle}/{hour}/{name}"
    )

    current_date = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d")

    if date == current_date:
        return [
            today_url,
            archive_url,
        ]

    return [
        archive_url,
        today_url,
    ]


def destination_path(
    date: str,
    cycle: str,
    forecast_hour: int,
) -> Path:
    directory = (
        Path("data/geps")
        / f"{date}_{cycle}z"
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return directory / (
        f"geps_{date}_{cycle}z_"
        f"f{forecast_hour:03d}_allmbrs.grib2"
    )


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


def valid_grib(
    path: Path,
    expected_members: int = 21,
) -> bool:
    try:
        return (
            grib_message_count(path)
            == expected_members
        )
    except (
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ):
        return False


def download_one(
    session: requests.Session,
    *,
    date: str,
    cycle: str,
    forecast_hour: int,
    expected_members: int,
    attempts: int = 4,
) -> tuple[str, str]:
    destination = destination_path(
        date,
        cycle,
        forecast_hour,
    )

    label = f"f{forecast_hour:03d}"

    if valid_grib(
        destination,
        expected_members,
    ):
        return "skipped", label

    temporary = destination.with_suffix(
        destination.suffix + ".part"
    )

    last_error = "No candidate URL succeeded."

    for url in candidate_urls(
        date,
        cycle,
        forecast_hour,
    ):
        for attempt in range(
            1,
            attempts + 1,
        ):
            temporary.unlink(
                missing_ok=True
            )

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

                    if not first_chunk.startswith(
                        b"GRIB"
                    ):
                        preview = (
                            first_chunk[:200]
                            .decode(
                                "utf-8",
                                errors="replace",
                            )
                        )

                        raise RuntimeError(
                            "Response was not GRIB data: "
                            f"{preview!r}"
                        )

                    with temporary.open(
                        "wb"
                    ) as output:
                        output.write(
                            first_chunk
                        )

                        for chunk in chunks:
                            if chunk:
                                output.write(
                                    chunk
                                )

                message_count = (
                    grib_message_count(
                        temporary
                    )
                )

                if (
                    message_count
                    != expected_members
                ):
                    raise RuntimeError(
                        "Expected "
                        f"{expected_members} GEPS "
                        "member messages, found "
                        f"{message_count}."
                    )

                temporary.replace(
                    destination
                )

                size_mb = (
                    destination.stat().st_size
                    / 1_000_000
                )

                return (
                    "downloaded",
                    f"{label} "
                    f"({message_count} members, "
                    f"{size_mb:.2f} MB)",
                )

            except (
                requests.RequestException,
                RuntimeError,
                OSError,
            ) as error:
                last_error = str(error)

                temporary.unlink(
                    missing_ok=True
                )

                if attempt < attempts:
                    time.sleep(
                        min(
                            20,
                            2 ** attempt,
                        )
                    )

    return (
        "failed",
        f"{label}: {last_error}",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download Canadian GEPS global "
            "2-meter-temperature ensemble files."
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
        "--expected-members",
        type=int,
        default=21,
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

    if args.expected_members <= 0:
        raise SystemExit(
            "--expected-members must be positive."
        )

    forecast_hours = list(
        range(
            0,
            args.max_hour + 1,
            args.step,
        )
    )

    print(
        f"GEPS initialization: "
        f"{args.date} {args.cycle}Z"
    )

    print(
        f"Forecast files requested: "
        f"{len(forecast_hours)}"
    )

    print(
        f"Expected members per file: "
        f"{args.expected_members}"
    )

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    downloaded = 0
    skipped = 0
    failures: list[str] = []

    for forecast_hour in forecast_hours:
        status, message = download_one(
            session,
            date=args.date,
            cycle=args.cycle,
            forecast_hour=forecast_hour,
            expected_members=(
                args.expected_members
            ),
        )

        print(
            f"[{status.upper():10}] "
            f"{message}",
            flush=True,
        )

        if status == "downloaded":
            downloaded += 1
        elif status == "skipped":
            skipped += 1
        else:
            failures.append(
                message
            )

        time.sleep(
            args.pause
        )

    run_directory = (
        Path("data/geps")
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
            f"Failures recorded in "
            f"{failure_path}"
        )

        raise SystemExit(2)


if __name__ == "__main__":
    main()
