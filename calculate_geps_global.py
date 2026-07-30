from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
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


FILE_PATTERN = re.compile(
    r"_f(\d{3})_allmbrs\.grib2$"
)


def parse_date(value: str) -> str:
    try:
        datetime.strptime(
            value,
            "%Y%m%d",
        )
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Date must use YYYYMMDD format."
        ) from error

    return value


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


def member_label(
    perturbation_number: int,
    ensemble_type: int | None,
) -> str:
    control_types = {
        0,
        1,
        5,
    }

    if (
        perturbation_number == 0
        or ensemble_type in control_types
    ):
        return "c00"

    return (
        f"p{perturbation_number:02d}"
    )


def forecast_hour_from_name(
    filename: str,
) -> int:
    match = FILE_PATTERN.search(
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


def point_weights(
    handle: Any,
) -> np.ndarray:
    latitude = np.asarray(
        codes_get_array(
            handle,
            "latitudes",
        ),
        dtype=np.float64,
    )

    weights = np.cos(
        np.deg2rad(latitude)
    )

    # Numerical protection at ±90°.
    weights = np.maximum(
        weights,
        0.0,
    )

    return weights


def global_temperature(
    handle: Any,
    weights: np.ndarray,
) -> float:
    values = np.asarray(
        codes_get_values(handle),
        dtype=np.float64,
    )

    if len(values) != len(weights):
        raise ValueError(
            "Temperature and latitude-weight "
            "arrays have different sizes."
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
            "Temperature message contains "
            "no valid grid values."
        )

    denominator = np.sum(
        weights[valid]
    )

    if denominator <= 0:
        raise ValueError(
            "Invalid latitude-weight total."
        )

    global_kelvin = (
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
        or global_kelvin > 100
    ):
        return (
            float(global_kelvin)
            - 273.15
        )

    return float(
        global_kelvin
    )


def process_file(
    file_path: Path,
    initialization: pd.Timestamp,
) -> list[dict[str, object]]:
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

    cached_weights: (
        np.ndarray | None
    ) = None

    expected_points: int | None = None

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
                        point_weights(
                            handle
                        )
                    )

                    expected_points = (
                        len(
                            cached_weights
                        )
                    )

                if (
                    expected_points
                    != number_of_points
                ):
                    raise ValueError(
                        "Member grid size differs "
                        "from the first member."
                    )

                raw_number = safe_get(
                    handle,
                    "perturbationNumber",
                    message_index - 1,
                )

                perturbation_number = int(
                    raw_number
                )

                raw_type = safe_get(
                    handle,
                    "typeOfEnsembleForecast",
                    None,
                )

                ensemble_type = (
                    int(raw_type)
                    if raw_type is not None
                    else None
                )

                temperature_c = (
                    global_temperature(
                        handle,
                        cached_weights,
                    )
                )

                records.append(
                    {
                        "member": member_label(
                            perturbation_number,
                            ensemble_type,
                        ),
                        "perturbation_number":
                            perturbation_number,
                        "type_of_ensemble_forecast":
                            ensemble_type,
                        "initialization_utc":
                            initialization,
                        "forecast_hour":
                            forecast_hour,
                        "valid_time_utc":
                            valid_time,
                        "global_temperature_c":
                            temperature_c,
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

    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Calculate area-weighted global "
            "2-meter temperatures for all GEPS "
            "members."
        )
    )

    parser.add_argument(
        "--date",
        required=True,
        type=parse_date,
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
        "--expected-members",
        type=int,
        default=21,
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

    initialization = pd.Timestamp(
        datetime.strptime(
            f"{args.date}{args.cycle}",
            "%Y%m%d%H",
        ),
        tz="UTC",
    )

    input_directory = (
        Path("data/geps")
        / f"{args.date}_{args.cycle}z"
    )

    files = sorted(
        input_directory.glob(
            "*_allmbrs.grib2"
        )
    )

    if not files:
        raise FileNotFoundError(
            "No GEPS all-member files found "
            f"in {input_directory}"
        )

    print(
        f"GEPS files found: {len(files)}"
    )

    records: list[
        dict[str, object]
    ] = []

    failures: list[str] = []

    for index, file_path in enumerate(
        files,
        start=1,
    ):
        print(
            f"[{index}/{len(files)}] "
            f"Processing {file_path.name}",
            flush=True,
        )

        try:
            file_records = (
                process_file(
                    file_path,
                    initialization,
                )
            )

            if (
                len(file_records)
                != args.expected_members
            ):
                raise ValueError(
                    "Expected "
                    f"{args.expected_members} "
                    "members, found "
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

    if not records:
        raise RuntimeError(
            "No GEPS files processed "
            "successfully."
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

    duplicates = (
        six_hourly.duplicated(
            subset=[
                "member",
                "forecast_hour",
            ],
            keep=False,
        )
    )

    if duplicates.any():
        print(
            "\nWARNING: duplicate member labels "
            "were detected:"
        )

        print(
            six_hourly.loc[
                duplicates,
                [
                    "forecast_hour",
                    "member",
                    "perturbation_number",
                    "type_of_ensemble_forecast",
                    "message_index",
                ],
            ].to_string(index=False)
        )

        raise RuntimeError(
            "GEPS member labels are not unique."
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

    daily_members[
        "complete_day"
    ] = (
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

    summary = summary.merge(
        quantiles,
        on="date_utc",
        how="left",
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
            complete["member"] != "c00"
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
            control,
            on="date_utc",
            how="left",
        )
        .merge(
            perturbed_mean,
            on="date_utc",
            how="left",
        )
        .sort_values(
            "date_utc"
        )
        .reset_index(drop=True)
    )

    summary[
        "complete_ensemble"
    ] = (
        summary[
            "members_available"
        ]
        == args.expected_members
    )

    output_directory = Path(
        "output"
    )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    prefix = (
        f"geps_{args.date}_"
        f"{args.cycle}z"
    )

    six_hourly_path = (
        output_directory
        / f"{prefix}_global_"
        "6hourly_members.csv"
    )

    daily_members_path = (
        output_directory
        / f"{prefix}_global_"
        "daily_members.csv"
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
        )
        .dt.strftime("%Y-%m-%d")
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
            / f"{prefix}_"
            "processing_failures.txt"
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
            f"See {failure_path}"
        )

    print(
        "\nGEPS daily ensemble summary:"
    )

    print(
        summary.to_string(
            index=False
        )
    )

    print("\nCreated:")
    print(six_hourly_path)
    print(daily_members_path)
    print(summary_path)
    print(json_path)


if __name__ == "__main__":
    main()
