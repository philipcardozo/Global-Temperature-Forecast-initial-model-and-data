from __future__ import annotations

import argparse
import re
from pathlib import Path

import cfgrib
import numpy as np
import pandas as pd
import xarray as xr


FILE_PATTERN = re.compile(
    r"_f(\d{3})\.grib2$"
)


def find_temperature(
    dataset: xr.Dataset,
) -> xr.DataArray:
    for name in (
        "t2m",
        "2t",
        "t",
    ):
        if name in dataset.data_vars:
            return dataset[name]

    variables = list(
        dataset.data_vars
    )

    if len(variables) == 1:
        return dataset[
            variables[0]
        ]

    raise KeyError(
        "Could not identify 2-meter temperature. "
        f"Variables found: {variables}"
    )


def remove_duplicate_longitude(
    temperature: xr.DataArray,
    longitude_name: str,
) -> xr.DataArray:
    longitudes = np.asarray(
        temperature[
            longitude_name
        ].values,
        dtype=float,
    )

    rounded = np.round(
        longitudes,
        decimals=6,
    )

    _, indices = np.unique(
        rounded,
        return_index=True,
    )

    if len(indices) == len(longitudes):
        return temperature

    return temperature.isel(
        {
            longitude_name:
            np.sort(indices)
        }
    )


def to_utc_timestamp(
    value: object,
) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)

    if timestamp.tzinfo is None:
        return timestamp.tz_localize(
            "UTC"
        )

    return timestamp.tz_convert(
        "UTC"
    )


def process_file(
    file_path: Path,
) -> dict[str, object]:
    match = FILE_PATTERN.search(
        file_path.name
    )

    if not match:
        raise ValueError(
            f"Unexpected filename: {file_path.name}"
        )

    forecast_hour = int(
        match.group(1)
    )

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
            raise KeyError(
                "Latitude coordinate not found."
            )

        if longitude_name not in temperature.coords:
            raise KeyError(
                "Longitude coordinate not found."
            )

        temperature = remove_duplicate_longitude(
            temperature,
            longitude_name,
        )

        latitude = temperature[
            latitude_name
        ]

        latitude_weights = xr.DataArray(
            np.cos(
                np.deg2rad(
                    latitude.values
                )
            ),
            coords={
                latitude_name:
                latitude.values
            },
            dims=[
                latitude_name
            ],
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

        global_value = float(
            global_kelvin.values
        )

        units = str(
            temperature.attrs.get(
                "units",
                "",
            )
        ).lower()

        if (
            units in {"k", "kelvin"}
            or global_value > 100
        ):
            global_celsius = (
                global_value - 273.15
            )
        else:
            global_celsius = (
                global_value
            )

        if "valid_time" in dataset.coords:
            valid_time = to_utc_timestamp(
                dataset[
                    "valid_time"
                ].values
            )
        else:
            initialization = to_utc_timestamp(
                dataset["time"].values
            )

            if "step" in dataset.coords:
                step = pd.Timedelta(
                    dataset["step"].values
                )
            else:
                step = pd.Timedelta(
                    hours=forecast_hour
                )

            valid_time = (
                initialization + step
            )

        initialization_time = (
            valid_time
            - pd.Timedelta(
                hours=forecast_hour
            )
        )

        return {
            "initialization_utc":
                initialization_time,
            "forecast_hour":
                forecast_hour,
            "valid_time_utc":
                valid_time,
            "global_temperature_c":
                global_celsius,
            "source_file":
                file_path.name,
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
        choices=("00", "12"),
    )

    parser.add_argument(
        "--step",
        type=int,
        default=6,
    )

    args = parser.parse_args()

    expected_snapshots = (
        24 // args.step
    )

    input_directory = (
        Path("data/gdps")
        / f"{args.date}_{args.cycle}z"
    )

    files = sorted(
        input_directory.glob(
            "*.grib2"
        )
    )

    if not files:
        raise FileNotFoundError(
            f"No GDPS files found in "
            f"{input_directory}"
        )

    print(
        f"GDPS files found: {len(files)}"
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
            records.append(
                process_file(
                    file_path
                )
            )
        except Exception as error:
            message = (
                f"{file_path}: "
                f"{type(error).__name__}: "
                f"{error}"
            )

            failures.append(message)
            print(
                f"FAILED: {message}"
            )

    if not records:
        raise RuntimeError(
            "No GDPS files processed successfully."
        )

    six_hourly = pd.DataFrame(
        records
    )

    six_hourly[
        "valid_time_utc"
    ] = pd.to_datetime(
        six_hourly[
            "valid_time_utc"
        ],
        utc=True,
    )

    six_hourly[
        "initialization_utc"
    ] = pd.to_datetime(
        six_hourly[
            "initialization_utc"
        ],
        utc=True,
    )

    six_hourly = (
        six_hourly
        .sort_values(
            "valid_time_utc"
        )
        .reset_index(drop=True)
    )

    six_hourly[
        "date_utc"
    ] = (
        six_hourly[
            "valid_time_utc"
        ].dt.floor("D")
    )

    daily = (
        six_hourly
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

    daily[
        "complete_day"
    ] = (
        daily["snapshots"]
        == expected_snapshots
    )

    complete = daily[
        daily["complete_day"]
    ].copy()

    output_directory = Path(
        "output"
    )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    prefix = (
        f"gdps_{args.date}_"
        f"{args.cycle}z"
    )

    six_hourly_path = (
        output_directory
        / f"{prefix}_global_6hourly.csv"
    )

    daily_path = (
        output_directory
        / f"{prefix}_global_daily.csv"
    )

    complete_path = (
        output_directory
        / f"{prefix}_global_daily_complete.csv"
    )

    json_path = (
        output_directory
        / f"{prefix}_global_daily_complete.json"
    )

    six_hourly.to_csv(
        six_hourly_path,
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

    json_frame = complete.copy()

    json_frame[
        "date_utc"
    ] = pd.to_datetime(
        json_frame["date_utc"],
        utc=True,
    ).dt.strftime(
        "%Y-%m-%d"
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
            f"Processing failures: "
            f"{len(failures)}"
        )

    print(
        "\nGDPS daily whole-Earth "
        "temperatures:"
    )

    print(
        daily.to_string(
            index=False
        )
    )

    print("\nCreated:")
    print(six_hourly_path)
    print(daily_path)
    print(complete_path)
    print(json_path)


if __name__ == "__main__":
    main()
