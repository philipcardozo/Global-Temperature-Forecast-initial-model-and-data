from __future__ import annotations

import argparse
import bz2
import re
import subprocess
import time
from pathlib import Path

import requests


BASE_URL = (
    "https://opendata.dwd.de/weather/nwp/"
    "icon/grib"
)

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

    return value


def remote_filename(
    date: str,
    cycle: str,
    forecast_hour: int,
) -> str:
    return (
        "icon_global_icosahedral_single-level_"
        f"{date}{cycle}_"
        f"{forecast_hour:03d}_"
        "T_2M.grib2.bz2"
    )


def remote_url(
    date: str,
    cycle: str,
    forecast_hour: int,
) -> str:
    return (
        f"{BASE_URL}/{cycle}/t_2m/"
        f"{remote_filename(date, cycle, forecast_hour)}"
    )


def destination_path(
    date: str,
    cycle: str,
    forecast_hour: int,
) -> Path:
    directory = (
        Path("data/icon")
        / f"{date}_{cycle}z"
        / "native"
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return directory / (
        "icon_global_icosahedral_single-level_"
        f"{date}{cycle}_"
        f"{forecast_hour:03d}_"
        "T_2M.grib2"
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


def valid_grib(path: Path) -> bool:
    try:
        return grib_message_count(path) == 1
    except (
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ):
        return False


def decompress_bz2(
    compressed_path: Path,
    decompressed_path: Path,
) -> None:
    temporary_output = decompressed_path.with_suffix(
        decompressed_path.suffix + ".part"
    )

    temporary_output.unlink(
        missing_ok=True
    )

    decompressor = bz2.BZ2Decompressor()

    with compressed_path.open("rb") as source:
        with temporary_output.open("wb") as destination:
            while True:
                compressed_chunk = source.read(
                    1024 * 1024
                )

                if not compressed_chunk:
                    break

                destination.write(
                    decompressor.decompress(
                        compressed_chunk
                    )
                )

    if not valid_grib(temporary_output):
        temporary_output.unlink(
            missing_ok=True
        )

        raise RuntimeError(
            "Decompressed file failed GRIB validation."
        )

    temporary_output.replace(
        decompressed_path
    )


def download_one(
    session: requests.Session,
    *,
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

    url = remote_url(
        date,
        cycle,
        forecast_hour,
    )

    compressed_path = destination.with_suffix(
        ".grib2.bz2.part"
    )

    for attempt in range(1, attempts + 1):
        compressed_path.unlink(
            missing_ok=True
        )

        destination.unlink(
            missing_ok=True
        )

        try:
            with session.get(
                url,
                stream=True,
                timeout=(30, 240),
            ) as response:
                if response.status_code == 404:
                    return (
                        "failed",
                        f"{label}: file not available at DWD",
                    )

                response.raise_for_status()

                chunks = response.iter_content(
                    chunk_size=1024 * 1024
                )

                first_chunk = next(
                    chunks,
                    b"",
                )

                if not first_chunk.startswith(b"BZh"):
                    preview = first_chunk[:150].decode(
                        "utf-8",
                        errors="replace",
                    )

                    raise RuntimeError(
                        "Response was not a bzip2 file: "
                        f"{preview!r}"
                    )

                with compressed_path.open("wb") as output:
                    output.write(first_chunk)

                    for chunk in chunks:
                        if chunk:
                            output.write(chunk)

            decompress_bz2(
                compressed_path,
                destination,
            )

            compressed_path.unlink(
                missing_ok=True
            )

            size_mb = (
                destination.stat().st_size
                / 1_000_000
            )

            return (
                "downloaded",
                f"{label} ({size_mb:.2f} MB decompressed)",
            )

        except (
            requests.RequestException,
            RuntimeError,
            OSError,
            EOFError,
        ) as error:
            compressed_path.unlink(
                missing_ok=True
            )

            destination.unlink(
                missing_ok=True
            )

            if attempt == attempts:
                return (
                    "failed",
                    f"{label}: {error}",
                )

            time.sleep(
                min(20, 2 ** attempt)
            )

    return "failed", f"{label}: unknown failure"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download deterministic global ICON "
            "2-meter-temperature fields."
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
        choices=("00", "06", "12", "18"),
    )

    parser.add_argument(
        "--max-hour",
        type=int,
        default=180,
    )

    parser.add_argument(
        "--step",
        type=int,
        default=6,
    )

    parser.add_argument(
        "--pause",
        type=float,
        default=0.20,
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
        f"ICON initialization: "
        f"{args.date} {args.cycle}Z"
    )

    print(
        f"Forecast fields requested: "
        f"{len(forecast_hours)}"
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
            failures.append(
                message
            )

        time.sleep(
            args.pause
        )

    run_directory = (
        Path("data/icon")
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
            f"Failures saved to {failure_path}"
        )

        raise SystemExit(2)


if __name__ == "__main__":
    main()
