from __future__ import annotations

import argparse
import re
from pathlib import Path

import cfgrib
import numpy as np
import pandas as pd
import xarray as xr


MEMBER_FILE_PATTERN = re.compile(
    r"_(c00|p\d{2})_f(\d{3})\.grib2$"
)


def find_temperature(
    dataset: xr.Dataset,
) -> xr.DataArray:
    for variable_name in ("t2m", "2t", "t"):
        if variable_name in dataset.data_vars:
            return dataset[variable_name]

    variables = list(dataset.data_vars)

    if len(variables) == 1:
        return dataset[variables[0]]

    raise KeyError(
        "Could not identify 2-meter temperature. "
        f"Variables found: {variables}"
    )


def utc_timestamp(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)

    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")

    return timestamp.tz_convert("UTC")


def remove_duplicate_longitude(
    temperature: xr.DataArray,
    longitude_name: str,
) -> xr.DataArray:
    longitude_values = np.asarray(
        temperature[longitude_name].values
    )

    rounded = np.round(
        longitude_values.astype(float),
        decimals=6,
    )

    _, unique_indices = np.unique(
        rounded,
        return_index=True,
    )

    if len(unique_indices) == len(longitude_values):
        return temperature

    return temperature.isel(
        {
            longitude_name: np.sort(
                unique_indices
            )
        }
    )


def process_file(file_path: Path) -> dict[str, object]:
    match = MEMBER_FILE_PATTERN.search(
        file_path.name
    )

    if not match:
        raise ValueError(
            f"Unexpected filename: {file_path.name}"
        )

    member = match.group(1)
    forecast_hour = int(match.group(2))

    dataset = cfgrib.open_dataset(
        file_path,
        indexpath="",
    )

    try:
        temperature = find_temperature(
            dataset
        ).squeeze(drop=True)

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

        if latitude_name not in temperature.coords:
            raise KeyError("Latitude coordinate not found.")

        if longitude_name not in temperature.coords:
            raise KeyError("Longitude coordinate not found.")

        temperature = remove_duplicate_longitude(
            temperature,
            longitude_name,
        )

        latitude = temperature[latitude_name]

        # Regular latitude-longitude grid:
        # grid-cell area is proportional to cos(latitude).
        latitude_weights = np.cos(
            np.deg2rad(latitude)
        )

        global_kelvin = temperature.weighted(
            latitude_weights
        ).mean(
            dim=(latitude_name, longitude_name),
            skipna=True,
        )

        global_celsius = (
            float(global_kelvin.values) - 273.15
        )

        if "valid_time" in dataset.coords:
            valid_time = utc_timestamp(
                dataset["valid_time"].values
            )
        else:
            initialization = utc_timestamp(
                dataset["time"].values
            )

            step = pd.Timedelta(
                dataset["step"].values
            )

            valid_time = initialization + step

        initialization_time = (
            valid_time
            - pd.Timedelta(
                hours=forecast_hour
            )
        )

        return {
            "member": member,
            "initialization_utc": initialization_time,
            "forecast_hour": forecast_hour,
            "valid_time_utc": valid_time,
            "global_temperature_c": global_celsius,
            "file": file_path.name,
        }

    finally:
        dataset.close()


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--date",
        required=True,
    )

    parser.add_argument(
        "--cycle",
        default="00",
        choices=("00", "06", "12", "18"),
    )

    parser.add_argument(
        "--step",
        type=int,
        default=6,
    )

    parser.add_argument(
        "--expected-members",
        type=int,
        default=31,
    )

    args = parser.parse_args()

    if 24 % args.step != 0:
        raise SystemExit(
            "--step must divide evenly into 24 hours."
        )

    expected_snapshots = 24 // args.step

    input_directory = (
        Path("data/gefs")
        / f"{args.date}_{args.cycle}z"
    )

    output_directory = Path("output")
    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    files = sorted(
        input_directory.glob("*/*.grib2")
    )

    if not files:
        raise FileNotFoundError(
            f"No GRIB2 files found under "
            f"{input_directory}"
        )

    print(f"Files found: {len(files)}")

    records: list[dict[str, object]] = []
    failures: list[str] = []

    for number, file_path in enumerate(
        files,
        start=1,
    ):
        print(
            f"[{number}/{len(files)}] "
            f"Processing {file_path.name}",
            flush=True,
        )

        try:
            records.append(
                process_file(file_path)
            )
        except Exception as error:
            message = (
                f"{file_path}: "
                f"{type(error).__name__}: {error}"
            )

            failures.append(message)
            print(f"FAILED: {message}")

    if not records:
        raise RuntimeError(
            "No files were processed successfully."
        )

    six_hourly = pd.DataFrame(records)

    six_hourly["valid_time_utc"] = pd.to_datetime(
        six_hourly["valid_time_utc"],
        utc=True,
    )

    six_hourly["initialization_utc"] = pd.to_datetime(
        six_hourly["initialization_utc"],
        utc=True,
    )

    six_hourly = six_hourly.sort_values(
        ["member", "valid_time_utc"]
    ).reset_index(drop=True)

    six_hourly["date_utc"] = (
        six_hourly["valid_time_utc"].dt.floor("D")
    )

    daily_members = (
        six_hourly.groupby(
            ["member", "date_utc"],
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
        complete.groupby(
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
        complete.groupby("date_utc")[
            "global_temperature_c"
        ]
        .quantile(
            [0.05, 0.25, 0.75, 0.95]
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
                "control_c"
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
        .sort_values("date_utc")
        .reset_index(drop=True)
    )

    summary["complete_ensemble"] = (
        summary["members_available"]
        == args.expected_members
    )

    prefix = (
        f"gefs_{args.date}_{args.cycle}z"
    )

    six_hourly_path = (
        output_directory
        / f"{prefix}_global_6hourly_members.csv"
    )

    daily_members_path = (
        output_directory
        / f"{prefix}_global_daily_members.csv"
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
        json_frame["date_utc"]
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
            / f"{prefix}_processing_failures.txt"
        )

        failure_path.write_text(
            "\n".join(failures) + "\n",
            encoding="utf-8",
        )

        print(
            f"\nProcessing failures: "
            f"{len(failures)}"
        )
        print(f"See {failure_path}")

    print("\nGEFS daily ensemble summary:")
    print(summary.to_string(index=False))

    print("\nCreated:")
    print(six_hourly_path)
    print(daily_members_path)
    print(summary_path)
    print(json_path)


if __name__ == "__main__":
    main()
