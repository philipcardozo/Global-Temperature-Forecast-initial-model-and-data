from __future__ import annotations

import argparse
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


BASE_URL = (
    "https://nomads.ncep.noaa.gov/cgi-bin/"
    "filter_gefs_atmos_0p50a.pl"
)

ALL_MEMBERS = ["c00"] + [
    f"p{number:02d}" for number in range(1, 31)
]


class RateLimiter:
    """Limit how quickly requests begin."""

    def __init__(self, interval_seconds: float) -> None:
        self.interval = interval_seconds
        self.lock = threading.Lock()
        self.next_allowed = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            wait_seconds = max(0.0, self.next_allowed - now)

            self.next_allowed = (
                max(self.next_allowed, now) + self.interval
            )

        if wait_seconds > 0:
            time.sleep(wait_seconds)


def parse_members(value: str) -> list[str]:
    if value.strip().lower() == "all":
        return ALL_MEMBERS.copy()

    members = [
        item.strip().lower()
        for item in value.split(",")
        if item.strip()
    ]

    invalid = [
        member
        for member in members
        if member not in ALL_MEMBERS
    ]

    if invalid:
        raise argparse.ArgumentTypeError(
            f"Invalid members: {invalid}. "
            "Use c00,p01,...,p30 or all."
        )

    return members


def validate_date(value: str) -> str:
    if not re.fullmatch(r"\d{8}", value):
        raise argparse.ArgumentTypeError(
            "Date must use YYYYMMDD format."
        )

    return value


def remote_filename(
    member: str,
    cycle: str,
    forecast_hour: int,
) -> str:
    # c00 becomes gec00; p01 becomes gep01.
    return (
        f"ge{member}.t{cycle}z."
        f"pgrb2a.0p50.f{forecast_hour:03d}"
    )


def request_parameters(
    date: str,
    cycle: str,
    member: str,
    forecast_hour: int,
) -> dict[str, str]:
    return {
        "file": remote_filename(
            member,
            cycle,
            forecast_hour,
        ),
        "var_TMP": "on",
        "lev_2_m_above_ground": "on",
        "subregion": "",
        "leftlon": "0",
        "rightlon": "360",
        "toplat": "90",
        "bottomlat": "-90",
        "dir": (
            f"/gefs.{date}/{cycle}/"
            "atmos/pgrb2ap5"
        ),
    }


def destination_path(
    date: str,
    cycle: str,
    member: str,
    forecast_hour: int,
) -> Path:
    return (
        Path("data/gefs")
        / f"{date}_{cycle}z"
        / member
        / (
            f"gefs_{date}_{cycle}z_"
            f"{member}_f{forecast_hour:03d}.grib2"
        )
    )


def is_valid_grib(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 8:
        return False

    with path.open("rb") as file:
        return file.read(4) == b"GRIB"


def download_one(
    *,
    date: str,
    cycle: str,
    member: str,
    forecast_hour: int,
    limiter: RateLimiter,
    attempts: int = 5,
) -> tuple[str, str]:
    destination = destination_path(
        date,
        cycle,
        member,
        forecast_hour,
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    label = f"{member} f{forecast_hour:03d}"

    if is_valid_grib(destination):
        return "skipped", label

    partial = destination.with_suffix(
        destination.suffix + ".part"
    )

    params = request_parameters(
        date,
        cycle,
        member,
        forecast_hour,
    )

    for attempt in range(1, attempts + 1):
        partial.unlink(missing_ok=True)

        try:
            limiter.wait()

            with requests.get(
                BASE_URL,
                params=params,
                stream=True,
                timeout=(30, 240),
            ) as response:
                response.raise_for_status()

                chunks = response.iter_content(
                    chunk_size=1024 * 1024
                )

                first_chunk = next(chunks, b"")

                if not first_chunk.startswith(b"GRIB"):
                    preview = first_chunk[:200].decode(
                        "utf-8",
                        errors="replace",
                    )

                    raise RuntimeError(
                        "NOAA did not return GRIB data. "
                        f"Response begins: {preview!r}"
                    )

                with partial.open("wb") as output:
                    output.write(first_chunk)

                    for chunk in chunks:
                        if chunk:
                            output.write(chunk)

            if not is_valid_grib(partial):
                raise RuntimeError(
                    "Downloaded file failed GRIB validation."
                )

            partial.replace(destination)

            size_mb = destination.stat().st_size / 1_000_000

            return (
                "downloaded",
                f"{label} ({size_mb:.2f} MB)",
            )

        except (
            requests.RequestException,
            RuntimeError,
        ) as error:
            partial.unlink(missing_ok=True)

            if attempt == attempts:
                return (
                    "failed",
                    f"{label}: {error}",
                )

            time.sleep(min(30, 2 ** (attempt - 1)))

    return "failed", f"{label}: unknown failure"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download GEFS 2-meter global-temperature fields."
        )
    )

    parser.add_argument(
        "--date",
        required=True,
        type=validate_date,
        help="Initialization date in YYYYMMDD format.",
    )

    parser.add_argument(
        "--cycle",
        default="00",
        choices=("00", "06", "12", "18"),
    )

    parser.add_argument(
        "--members",
        default="all",
        type=parse_members,
        help="all or comma-separated members.",
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
        "--workers",
        type=int,
        default=3,
    )

    parser.add_argument(
        "--request-interval",
        type=float,
        default=0.35,
        help="Minimum seconds between request starts.",
    )

    args = parser.parse_args()

    if args.max_hour < 0:
        raise SystemExit("--max-hour must be nonnegative.")

    if args.step <= 0:
        raise SystemExit("--step must be positive.")

    forecast_hours = list(
        range(0, args.max_hour + 1, args.step)
    )

    members: list[str] = args.members

    jobs = [
        (member, forecast_hour)
        for member in members
        for forecast_hour in forecast_hours
    ]

    print(
        f"GEFS initialization: "
        f"{args.date} {args.cycle}Z"
    )
    print(f"Members: {len(members)}")
    print(f"Forecast times per member: {len(forecast_hours)}")
    print(f"Total requested files: {len(jobs)}")

    limiter = RateLimiter(
        args.request_interval
    )

    counts: Counter[str] = Counter()
    failures: list[str] = []

    with ThreadPoolExecutor(
        max_workers=args.workers
    ) as executor:
        future_map = {
            executor.submit(
                download_one,
                date=args.date,
                cycle=args.cycle,
                member=member,
                forecast_hour=forecast_hour,
                limiter=limiter,
            ): (member, forecast_hour)
            for member, forecast_hour in jobs
        }

        for future in as_completed(future_map):
            status, message = future.result()
            counts[status] += 1

            print(
                f"[{status.upper():10}] {message}",
                flush=True,
            )

            if status == "failed":
                failures.append(message)

    print("\nDownload summary")
    print(f"Downloaded: {counts['downloaded']}")
    print(f"Skipped:    {counts['skipped']}")
    print(f"Failed:     {counts['failed']}")

    if failures:
        run_directory = (
            Path("data/gefs")
            / f"{args.date}_{args.cycle}z"
        )

        failure_file = (
            run_directory / "failed_downloads.txt"
        )

        failure_file.write_text(
            "\n".join(failures) + "\n",
            encoding="utf-8",
        )

        print(
            f"Failures saved to {failure_file}"
        )

        raise SystemExit(2)


if __name__ == "__main__":
    main()
