from __future__ import annotations

import argparse
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from ecmwf.opendata import Client


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
    expected_messages: int,
) -> bool:
    try:
        return (
            grib_message_count(path)
            == expected_messages
        )
    except (
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ):
        return False


def destination_paths(
    date: str,
    cycle: str,
    forecast_hour: int,
) -> tuple[Path, Path]:
    run_directory = (
        Path("data/ecmwf_ens")
        / f"{date}_{cycle}z"
    )

    perturbed_directory = (
        run_directory / "perturbed"
    )

    control_directory = (
        run_directory / "control"
    )

    perturbed_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    control_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    perturbed_path = (
        perturbed_directory
        / (
            f"ecmwf_ens_{date}_{cycle}z_"
            f"f{forecast_hour:03d}_"
            "perturbed.grib2"
        )
    )

    control_path = (
        control_directory
        / (
            f"ecmwf_ens_{date}_{cycle}z_"
            f"f{forecast_hour:03d}_"
            "control.grib2"
        )
    )

    return perturbed_path, control_path


def retrieve_with_validation(
    client: Client,
    *,
    request: dict[str, object],
    destination: Path,
    expected_messages: int,
    attempts: int = 3,
) -> tuple[str, str]:
    if valid_grib(
        destination,
        expected_messages,
    ):
        return (
            "skipped",
            destination.name,
        )

    temporary = destination.with_suffix(
        destination.suffix + ".part"
    )

    last_error = "Unknown retrieval failure."

    for attempt in range(1, attempts + 1):
        temporary.unlink(
            missing_ok=True
        )

        destination.unlink(
            missing_ok=True
        )

        try:
            client.retrieve(
                request=request,
                target=str(temporary),
            )

            message_count = (
                grib_message_count(
                    temporary
                )
            )

            if (
                message_count
                != expected_messages
            ):
                raise RuntimeError(
                    "Expected "
                    f"{expected_messages} GRIB messages, "
                    f"found {message_count}."
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
                (
                    f"{destination.name} "
                    f"({message_count} messages, "
                    f"{size_mb:.2f} MB)"
                ),
            )

        except Exception as error:
            last_error = (
                f"{type(error).__name__}: "
                f"{error}"
            )

            temporary.unlink(
                missing_ok=True
            )

            destination.unlink(
                missing_ok=True
            )

            if attempt < attempts:
                time.sleep(
                    min(20, 2 ** attempt)
                )

    return (
        "failed",
        (
            f"{destination.name}: "
            f"{last_error}"
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download ECMWF IFS ENS perturbed "
            "members and the IFS control forecast."
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
        "--expected-perturbed",
        type=int,
        default=50,
    )

    parser.add_argument(
        "--source",
        default="ecmwf",
        choices=(
            "ecmwf",
            "aws",
            "azure",
            "google",
        ),
    )

    parser.add_argument(
        "--pause",
        type=float,
        default=0.5,
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

    client = Client(
        source=args.source,
        model="ifs",
        resol="0p25",
        infer_stream_keyword=False,
    )

    print(
        f"ECMWF ENS initialization: "
        f"{args.date} {args.cycle}Z"
    )

    print(
        f"Forecast hours requested: "
        f"{len(forecast_hours)}"
    )

    print(
        "Expected trajectories per hour: "
        f"{args.expected_perturbed} perturbed "
        "+ 1 control"
    )

    downloaded = 0
    skipped = 0
    failures: list[str] = []

    for forecast_hour in forecast_hours:
        perturbed_path, control_path = (
            destination_paths(
                args.date,
                args.cycle,
                forecast_hour,
            )
        )

        perturbed_request = {
            "date": args.date,
            "time": int(args.cycle),
            "stream": "enfo",
            "type": "ef",
            "step": forecast_hour,
            "param": "2t",
            "levtype": "sfc",
        }

        control_request = {
            "date": args.date,
            "time": int(args.cycle),
            "stream": "oper",
            "type": "fc",
            "step": forecast_hour,
            "param": "2t",
            "levtype": "sfc",
        }

        status, message = (
            retrieve_with_validation(
                client,
                request=perturbed_request,
                destination=perturbed_path,
                expected_messages=(
                    args.expected_perturbed
                ),
            )
        )

        print(
            f"[PERTURBED {status.upper():10}] "
            f"f{forecast_hour:03d} {message}",
            flush=True,
        )

        if status == "downloaded":
            downloaded += 1
        elif status == "skipped":
            skipped += 1
        else:
            failures.append(
                f"f{forecast_hour:03d} "
                f"perturbed: {message}"
            )

        status, message = (
            retrieve_with_validation(
                client,
                request=control_request,
                destination=control_path,
                expected_messages=1,
            )
        )

        print(
            f"[CONTROL   {status.upper():10}] "
            f"f{forecast_hour:03d} {message}",
            flush=True,
        )

        if status == "downloaded":
            downloaded += 1
        elif status == "skipped":
            skipped += 1
        else:
            failures.append(
                f"f{forecast_hour:03d} "
                f"control: {message}"
            )

        time.sleep(
            args.pause
        )

    run_directory = (
        Path("data/ecmwf_ens")
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
    print(f"Downloaded files: {downloaded}")
    print(f"Skipped files:    {skipped}")
    print(f"Failed files:     {len(failures)}")

    if failures:
        print(
            f"Failures recorded in "
            f"{failure_path}"
        )

        raise SystemExit(2)


if __name__ == "__main__":
    main()
