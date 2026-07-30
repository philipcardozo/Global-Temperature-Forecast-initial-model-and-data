from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from eccodes import (
    codes_get,
    codes_get_array,
    codes_get_values,
    codes_grib_new_from_file,
    codes_release,
)


FORECAST_PATTERN = re.compile(
    r"_f(\d{3})_"
)


def safe_get(
    handle: Any,
    key: str,
    default: Any = None,
) -> Any:
    try:
        return codes_get(
            handle,
            key,
        )
    except Exception:
        return default


def forecast_hour_from_name(
    filename: str,
) -> int:
    match = FORECAST_PATTERN.search(
        filename
    )

    if not match:
        raise ValueError(
            "Could not identify forecast hour "
            f"from {filename}"
        )

    return int(
        match.group(1)
    )


def create_weights(
    handle: Any,
) -> np.ndarray:
    latitudes = np.asarray(
        codes_get_array(
            handle,
            "latitudes",
        ),
        dtype=np.float64,
    )

    weights = np.cos(
        np.deg2rad(latitudes)
    )

    return np.maximum(
        weights,
        0.0,
    )


def calculate_global_temperature(
    handle: Any,
    weights: np.ndarray,
) -> float:
    values = np.asarray(
        codes_get_values(handle),
        dtype=np.float64,
    )

    if len(values) != len(weights):
        raise ValueError(
            "Temperature values and latitude "
            "weights have different lengths."
        )

    valid = np.isfinite(values)

    missing_value = safe_get(
        handle,
        "missingValue",
        None,
    )

    if missing_value is not None:
        try:
            valid &= (
                values
                != float(missing_value)
            )
        except (
            TypeError,
            ValueError,
        ):
            pass

    if not np.any(valid):
        raise ValueError(
            "No valid temperature values."
        )

    denominator = np.sum(
        weights[valid]
    )

    global_value = (
        np.sum(
            values[valid]
            * weights[valid]
        )
        / denominator
    )

    units = str(
        safe_get(
            handle,
            "units",
            "",
        )
    ).strip().lower()

    if (
        units in {"k", "kelvin"}
        or global_value > 100
    ):
        return (
            float(global_value)
            - 273.15
        )

    return float(
        global_value
    )


def process_file(
    file_path: Path,
    *,
    initialization: pd.Timestamp,
    control: bool,
    cached_weights: np.ndarray | None,
) -> tuple[
    list[dict[str, object]],
    np.ndarray,
]:
    forecast_hour = (
        forecast_hour_from_name(
            file_path.name
        )
    )

    valid_time = (
        initialization
        + pd.Timedelta(
            hours=forecast_hour
        )
    )

    records: list[
        dict[str, object]
    ] = []

    message_index = 0

    with file_path.open("rb") as stream:
        while True:
            handle = (
                codes_grib_new_from_file(
                    stream
                )
            )

            if handle is None:
                break

            message_index += 1

            try:
                number_of_points = int(
                    safe_get(
                        handle,
                        "numberOfDataPoints",
                        0,
                    )
                )

                if cached_weights is None:
                    cached_weights = (
                        create_weights(
                            handle
                        )
                    )

                if (
                    len(cached_weights)
                    != number_of_points
                ):
                    raise ValueError(
                        "Unexpected grid size."
                    )

                if control:
                    member = "c00"
                    member_number = 0
                else:
                    raw_number = safe_get(
                        handle,
                        "number",
                        None,
                    )

                    if raw_number is None:
                        raw_number = safe_get(
                            handle,
                            "perturbationNumber",
                            message_index,
                        )

                    member_number = int(
                        raw_number
                    )

                    member = (
                        f"p{member_number:02d}"
                    )

                global_temperature_c = (
                    calculate_global_temperature(
                        handle,
                        cached_weights,
                    )
                )

                records.append(
                    {
                        "member": member,
                        "member_number":
                            member_number,
                        "member_type": (
                            "control"
                            if control
                            else "perturbed"
                        ),
                        "initialization_utc":
                            initialization,
                        "forecast_hour":
                            forecast_hour,
                        "valid_time_utc":
                            valid_time,
                        "global_temperature_c":
                            global_temperature_c,
                        "source_file":
                            file_path.name,
                        "message_index":
                            message_index,
                    }
                )

            finally:
                codes_release(
                    handle
                )

    if not records:
        raise RuntimeError(
            f"No GRIB messages found in "
            f"{file_path}"
        )

    if cached_weights is None:
        raise RuntimeError(
            "Latitude weights were not created."
        )

    return records, cached_weights


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--date",
        required=True,
    )

    parser.add_argument(
        "--cycle",
        default="00",
        choices=("00", "12"),
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

    args = parser.parse_args()

    if (
        args.step <= 0
        or 24 % args.step != 0
    ):
        raise SystemExit(
            "--step must be a positive "
            "divisor of 24."
        )

    expected_snapshots = (
        24 // args.step
    )

    expected_total_members = (
        args.expected_perturbed + 1
    )

    initialization = pd.Timestamp(
        datetime.strptime(
            f"{args.date}{args.cycle}",
            "%Y%m%d%H",
        ),
        tz="UTC",
    )

    run_directory = (
        Path("data/aifs_ens")
        / f"{args.date}_{args.cycle}z"
    )

    perturbed_files = sorted(
        (
            run_directory
            / "perturbed"
        ).glob(
            "*.grib2"
        )
    )

    control_files = sorted(
        (
            run_directory
            / "control"
        ).glob(
            "*.grib2"
        )
    )

    if not perturbed_files:
        raise FileNotFoundError(
            "No perturbed AIFS ENS files found."
        )

    if not control_files:
        raise FileNotFoundError(
            "No AIFS control files found."
        )

    print(
        "Perturbed files found:",
        len(perturbed_files),
    )

    print(
        "Control files found:",
        len(control_files),
    )

    records: list[
        dict[str, object]
    ] = []

    failures: list[str] = []

    cached_weights: np.ndarray | None = None

    total_files = (
        len(perturbed_files)
        + len(control_files)
    )

    current_index = 0

    for file_path in perturbed_files:
        current_index += 1

        print(
            f"[{current_index}/{total_files}] "
            f"Processing {file_path.name}",
            flush=True,
        )

        try:
            file_records, cached_weights = (
                process_file(
                    file_path,
                    initialization=initialization,
                    control=False,
                    cached_weights=cached_weights,
                )
            )

            if (
                len(file_records)
                != args.expected_perturbed
            ):
                raise ValueError(
                    "Expected "
                    f"{args.expected_perturbed} "
                    "perturbed members, found "
                    f"{len(file_records)}."
                )

            records.extend(
                file_records
            )

        except Exception as error:
            message = (
                f"{file_path}: "
                f"{type(error).__name__}: "
                f"{error}"
            )

            failures.append(
                message
            )

            print(
                f"FAILED: {message}"
            )

    for file_path in control_files:
        current_index += 1

        print(
            f"[{current_index}/{total_files}] "
            f"Processing {file_path.name}",
            flush=True,
        )

        try:
            file_records, cached_weights = (
                process_file(
                    file_path,
                    initialization=initialization,
                    control=True,
                    cached_weights=cached_weights,
                )
            )

            if len(file_records) != 1:
                raise ValueError(
                    "Expected one control field, "
                    f"found {len(file_records)}."
                )

            records.extend(
                file_records
            )

        except Exception as error:
            message = (
                f"{file_path}: "
                f"{type(error).__name__}: "
                f"{error}"
            )

            failures.append(
                message
            )

            print(
                f"FAILED: {message}"
            )

    if not records:
        raise RuntimeError(
            "No AIFS fields processed."
        )

    six_hourly = pd.DataFrame(
        records
    )

    six_hourly[
        "initialization_utc"
    ] = pd.to_datetime(
        six_hourly[
            "initialization_utc"
        ],
        utc=True,
    )

    six_hourly[
        "valid_time_utc"
    ] = pd.to_datetime(
        six_hourly[
            "valid_time_utc"
        ],
        utc=True,
    )

    duplicates = six_hourly.duplicated(
        subset=[
            "member",
            "forecast_hour",
        ],
        keep=False,
    )

    if duplicates.any():
        print(
            six_hourly.loc[
                duplicates,
                [
                    "member",
                    "forecast_hour",
                    "source_file",
                ],
            ].to_string(index=False)
        )

        raise RuntimeError(
            "Duplicate AIFS member-hour "
            "records detected."
        )

    six_hourly = (
        six_hourly
        .sort_values(
            [
                "member",
                "valid_time_utc",
            ]
        )
        .reset_index(drop=True)
    )

    six_hourly["date_utc"] = (
        six_hourly[
            "valid_time_utc"
        ].dt.floor("D")
    )

    daily_members = (
        six_hourly
        .groupby(
            [
                "member",
                "member_type",
                "date_utc",
            ],
            as_index=False,
        )
        .agg(
            global_temperature_c=(
                "global_temperature_c",
                "mean",
            ),
            snapshots=(
                "global_temperature_c",
                "count",
            ),
            minimum_snapshot_c=(
                "global_temperature_c",
                "min",
            ),
            maximum_snapshot_c=(
                "global_temperature_c",
                "max",
            ),
            minimum_forecast_hour=(
                "forecast_hour",
                "min",
            ),
            maximum_forecast_hour=(
                "forecast_hour",
                "max",
            ),
        )
    )

    daily_members["complete_day"] = (
        daily_members["snapshots"]
        == expected_snapshots
    )

    complete = daily_members[
        daily_members["complete_day"]
    ].copy()

    summary = (
        complete
        .groupby(
            "date_utc",
            as_index=False,
        )
        .agg(
            ensemble_mean_c=(
                "global_temperature_c",
                "mean",
            ),
            ensemble_median_c=(
                "global_temperature_c",
                "median",
            ),
            ensemble_std_c=(
                "global_temperature_c",
                "std",
            ),
            ensemble_min_c=(
                "global_temperature_c",
                "min",
            ),
            ensemble_max_c=(
                "global_temperature_c",
                "max",
            ),
            members_available=(
                "member",
                "nunique",
            ),
        )
    )

    quantiles = (
        complete
        .groupby("date_utc")[
            "global_temperature_c"
        ]
        .quantile(
            [
                0.05,
                0.25,
                0.75,
                0.95,
            ]
        )
        .unstack()
        .rename(
            columns={
                0.05: "p05_c",
                0.25: "p25_c",
                0.75: "p75_c",
                0.95: "p95_c",
            }
        )
        .reset_index()
    )

    control = (
        complete[
            complete["member"] == "c00"
        ][
            [
                "date_utc",
                "global_temperature_c",
            ]
        ]
        .rename(
            columns={
                "global_temperature_c":
                    "control_c",
            }
        )
    )

    perturbed_mean = (
        complete[
            complete["member_type"]
            == "perturbed"
        ]
        .groupby(
            "date_utc",
            as_index=False,
        )
        .agg(
            perturbed_mean_c=(
                "global_temperature_c",
                "mean",
            )
        )
    )

    summary = (
        summary
        .merge(
            quantiles,
            on="date_utc",
            how="left",
        )
        .merge(
            control,
            on="date_utc",
            how="left",
        )
        .merge(
            perturbed_mean,
            on="date_utc",
            how="left",
        )
        .sort_values("date_utc")
        .reset_index(drop=True)
    )

    summary["complete_ensemble"] = (
        summary["members_available"]
        == expected_total_members
    )

    output_directory = Path("output")

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    prefix = (
        f"aifs_ens_{args.date}_"
        f"{args.cycle}z"
    )

    six_hourly_path = (
        output_directory
        / (
            f"{prefix}_global_"
            "6hourly_members.csv"
        )
    )

    daily_members_path = (
        output_directory
        / (
            f"{prefix}_global_"
            "daily_members.csv"
        )
    )

    summary_path = (
        output_directory
        / f"{prefix}_daily_summary.csv"
    )

    json_path = (
        output_directory
        / f"{prefix}_daily_summary.json"
    )

    six_hourly.to_csv(
        six_hourly_path,
        index=False,
    )

    daily_members.to_csv(
        daily_members_path,
        index=False,
    )

    summary.to_csv(
        summary_path,
        index=False,
    )

    json_frame = summary.copy()

    json_frame["date_utc"] = (
        pd.to_datetime(
            json_frame["date_utc"],
            utc=True,
        ).dt.strftime("%Y-%m-%d")
    )

    json_path.write_text(
        json_frame.to_json(
            orient="records",
            indent=2,
        ),
        encoding="utf-8",
    )

    if failures:
        failure_path = (
            output_directory
            / (
                f"{prefix}_"
                "processing_failures.txt"
            )
        )

        failure_path.write_text(
            "\n".join(failures) + "\n",
            encoding="utf-8",
        )

        print(
            f"\nProcessing failures: "
            f"{len(failures)}"
        )

    print(
        "\nAIFS ENS daily summary:"
    )

    print(
        summary.to_string(index=False)
    )

    print("\nCreated:")
    print(six_hourly_path)
    print(daily_members_path)
    print(summary_path)
    print(json_path)


if __name__ == "__main__":
    main()
