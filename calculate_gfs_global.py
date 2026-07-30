from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

import cfgrib
import numpy as np
import pandas as pd
import xarray as xr


BASE_INPUT_DIRECTORY = Path("data/gfs")
OUTPUT_DIRECTORY = Path("output")

VALID_CYCLES = ("00", "06", "12", "18")
STEP_HOURS = 6


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
            "Calculate run-scoped whole-Earth GFS "
            "2-meter temperatures."
        )
    )

    parser.add_argument(
        "--date",
        required=True,
        type=valid_date,
    )

    parser.add_argument(
        "--cycle",
        default="00",
        choices=VALID_CYCLES,
    )

    parser.add_argument(
        "--max-hour",
        type=valid_max_hour,
        default=240,
    )

    return parser.parse_args()


def find_temperature_variable(
    dataset: xr.Dataset,
) -> xr.DataArray:
    candidates = ("t2m", "2t", "t")

    for name in candidates:
        if name in dataset.data_vars:
            return dataset[name]

    variables = list(dataset.data_vars)

    if len(variables) == 1:
        return dataset[variables[0]]

    raise KeyError(
        "Could not identify 2-meter temperature. "
        f"Variables found: {variables}"
    )


def remove_duplicate_longitude(
    temperature: xr.DataArray,
    longitude_name: str,
) -> xr.DataArray:
    longitudes = temperature[
        longitude_name
    ].values

    rounded = np.round(
        longitudes,
        6,
    )

    _, unique_indices = np.unique(
        rounded,
        return_index=True,
    )

    if len(unique_indices) != len(longitudes):
        temperature = temperature.isel(
            {
                longitude_name:
                    np.sort(unique_indices)
            }
        )

    return temperature


def as_utc_timestamp(
    value: object,
) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)

    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")

    return timestamp.tz_convert("UTC")


def calculate_global_mean(
    file_path: Path,
    initialization: pd.Timestamp,
) -> dict[str, object]:
    dataset = cfgrib.open_dataset(
        file_path,
        indexpath="",
    )

    try:
        temperature = (
            find_temperature_variable(dataset)
            .squeeze(drop=True)
        )

        latitude_name = (
            "latitude"
            if "latitude" in temperature.coords
            else "lat"
        )

        longitude_name = (
            "longitude"
            if "longitude" in temperature.coords
            else "lon"
        )

        temperature = remove_duplicate_longitude(
            temperature,
            longitude_name,
        )

        latitude = temperature[
            latitude_name
        ]

        latitude_weights = np.cos(
            np.deg2rad(latitude)
        )

        global_kelvin = (
            temperature
            .weighted(latitude_weights)
            .mean(
                dim=(
                    latitude_name,
                    longitude_name,
                ),
                skipna=True,
            )
        )

        global_celsius = (
            float(global_kelvin.values)
            - 273.15
        )

        valid_time = dataset.coords.get(
            "valid_time"
        )

        if valid_time is None:
            dataset_initialization = (
                as_utc_timestamp(
                    dataset["time"].values
                )
            )

            step = pd.Timedelta(
                dataset["step"].values
            )

            valid_timestamp = (
                dataset_initialization + step
            )

        else:
            valid_timestamp = (
                as_utc_timestamp(
                    valid_time.values
                )
            )

    finally:
        dataset.close()

    match = re.search(
        r"_f(\d{3})",
        file_path.name,
    )

    if match is None:
        raise ValueError(
            "Could not parse forecast hour from "
            f"{file_path.name}"
        )

    forecast_hour = int(
        match.group(1)
    )

    return {
        "file": file_path.name,
        "initialization_utc": initialization,
        "valid_time_utc": valid_timestamp,
        "forecast_hour": forecast_hour,
        "global_temperature_c": global_celsius,
    }


def main() -> None:
    args = parse_args()

    run_id = (
        f"{args.date}_{args.cycle}z"
    )

    input_directory = (
        BASE_INPUT_DIRECTORY / run_id
    )

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    expected_hours = list(
        range(
            0,
            args.max_hour + 1,
            STEP_HOURS,
        )
    )

    files = sorted(
        input_directory.glob(
            f"gfs_{args.date}_{args.cycle}z_"
            "f*.grib2"
        )
    )

    if not files:
        raise FileNotFoundError(
            "No GFS GRIB2 files found in "
            f"{input_directory}"
        )

    available_hours: list[int] = []

    for path in files:
        match = re.search(
            r"_f(\d{3})",
            path.name,
        )

        if match is not None:
            available_hours.append(
                int(match.group(1))
            )

    missing_hours = sorted(
        set(expected_hours)
        - set(available_hours)
    )

    unexpected_hours = sorted(
        set(available_hours)
        - set(expected_hours)
    )

    if missing_hours:
        raise RuntimeError(
            "Missing GFS forecast hours: "
            f"{missing_hours}"
        )

    if unexpected_hours:
        raise RuntimeError(
            "Unexpected GFS forecast hours: "
            f"{unexpected_hours}"
        )

    initialization = pd.Timestamp(
        datetime.strptime(
            args.date + args.cycle,
            "%Y%m%d%H",
        ),
        tz="UTC",
    )

    records: list[
        dict[str, object]
    ] = []

    failures: list[str] = []

    for file_path in files:
        print(
            f"Processing {file_path.name}"
        )

        try:
            records.append(
                calculate_global_mean(
                    file_path,
                    initialization,
                )
            )

        except Exception as error:
            failures.append(
                f"{file_path.name}: {error}"
            )

    if failures:
        raise RuntimeError(
            "GFS processing failures:\n"
            + "\n".join(failures)
        )

    hourly = (
        pd.DataFrame(records)
        .sort_values("forecast_hour")
        .reset_index(drop=True)
    )

    hourly["initialization_utc"] = (
        pd.to_datetime(
            hourly["initialization_utc"],
            utc=True,
        )
    )

    hourly["valid_time_utc"] = (
        pd.to_datetime(
            hourly["valid_time_utc"],
            utc=True,
        )
    )

    hourly["date_utc"] = (
        hourly["valid_time_utc"]
        .dt.floor("D")
    )

    daily = (
        hourly
        .groupby(
            "date_utc",
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
        )
    )

    daily["complete_day"] = (
        daily["snapshots"] == 4
    )

    complete = (
        daily.loc[
            daily["complete_day"]
        ]
        .reset_index(drop=True)
    )

    hourly_path = (
        OUTPUT_DIRECTORY
        / (
            f"gfs_{run_id}_"
            "global_6hourly.csv"
        )
    )

    daily_path = (
        OUTPUT_DIRECTORY
        / (
            f"gfs_{run_id}_"
            "global_daily.csv"
        )
    )

    complete_path = (
        OUTPUT_DIRECTORY
        / (
            f"gfs_{run_id}_"
            "global_daily_complete.csv"
        )
    )

    complete_json_path = (
        OUTPUT_DIRECTORY
        / (
            f"gfs_{run_id}_"
            "global_daily_complete.json"
        )
    )

    hourly.to_csv(
        hourly_path,
        index=False,
    )

    daily.to_csv(
        daily_path,
        index=False,
    )

    complete.to_csv(
        complete_path,
        index=False,
    )

    complete_json_path.write_text(
        complete.to_json(
            orient="records",
            date_format="iso",
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        "\nDaily whole-Earth GFS temperatures:"
    )

    print(
        daily.to_string(index=False)
    )

    print()
    print(
        f"Six-hourly records: {len(hourly)}"
    )

    print(
        f"Complete UTC days:  {len(complete)}"
    )

    print("\nCreated:")
    print(hourly_path)
    print(daily_path)
    print(complete_path)
    print(complete_json_path)


if __name__ == "__main__":
    main()
