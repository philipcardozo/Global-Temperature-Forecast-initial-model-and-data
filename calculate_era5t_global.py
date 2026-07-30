from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


INPUT_PATTERN = (
    "data/era5t/*/"
    "era5t_*_t2m_hourly.grib"
)

OUTPUT_DIRECTORY = Path("output")


def find_temperature(
    dataset: xr.Dataset,
) -> xr.DataArray:
    for variable in ("t2m", "2t", "t"):
        if variable in dataset.data_vars:
            return dataset[variable]

    variables = list(dataset.data_vars)

    if len(variables) == 1:
        return dataset[variables[0]]

    raise KeyError(
        "Could not identify 2-meter temperature. "
        f"Found: {variables}"
    )


def remove_duplicate_longitude(
    temperature: xr.DataArray,
    longitude_name: str,
) -> xr.DataArray:
    longitudes = np.asarray(
        temperature[longitude_name].values,
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


def extract_times(
    temperature: xr.DataArray,
) -> pd.DatetimeIndex:
    if "valid_time" in temperature.coords:
        values = np.asarray(
            temperature["valid_time"].values
        ).reshape(-1)

    elif "time" in temperature.coords:
        values = np.asarray(
            temperature["time"].values
        ).reshape(-1)

    else:
        raise KeyError(
            "No time coordinate found."
        )

    return pd.to_datetime(
        values,
        utc=True,
    )


def process_file(
    file_path: Path,
) -> pd.DataFrame:
    dataset = xr.open_dataset(
        file_path,
        engine="cfgrib",
        backend_kwargs={
            "indexpath": "",
        },
    )

    try:
        temperature = find_temperature(
            dataset
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

        latitude = temperature[latitude_name]

        # Keep the same spatial weighting used in the
        # existing GFS and GEFS calculations.
        latitude_weights = xr.DataArray(
            np.cos(
                np.deg2rad(latitude.values)
            ),
            coords={
                latitude_name: latitude.values
            },
            dims=[latitude_name],
        )

        global_kelvin = temperature.weighted(
            latitude_weights
        ).mean(
            dim=(
                latitude_name,
                longitude_name,
            ),
            skipna=True,
        )

        values = np.asarray(
            global_kelvin.values
        ).reshape(-1)

        units = str(
            temperature.attrs.get(
                "units",
                "",
            )
        ).lower()

        if units in {"k", "kelvin"} or np.nanmean(values) > 100:
            values = values - 273.15

        times = extract_times(
            temperature
        )

        if len(times) != len(values):
            raise ValueError(
                "Time and temperature dimensions "
                "have different lengths."
            )

        return pd.DataFrame(
            {
                "valid_time_utc": times,
                "era5t_global_c": values,
                "source_file": file_path.name,
            }
        )

    finally:
        dataset.close()


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    files = sorted(
        Path(".").glob(INPUT_PATTERN)
    )

    if not files:
        raise FileNotFoundError(
            "No ERA5T GRIB files found."
        )

    frames: list[pd.DataFrame] = []

    for index, file_path in enumerate(
        files,
        start=1,
    ):
        print(
            f"[{index}/{len(files)}] "
            f"Processing {file_path}"
        )

        frames.append(
            process_file(file_path)
        )

    hourly = pd.concat(
        frames,
        ignore_index=True,
    )

    hourly["valid_time_utc"] = pd.to_datetime(
        hourly["valid_time_utc"],
        utc=True,
    )

    hourly = (
        hourly
        .drop_duplicates(
            subset=["valid_time_utc"],
            keep="last",
        )
        .sort_values("valid_time_utc")
        .reset_index(drop=True)
    )

    hourly["date_utc"] = (
        hourly["valid_time_utc"]
        .dt.floor("D")
    )

    hourly["hour_utc"] = (
        hourly["valid_time_utc"]
        .dt.hour
    )

    full_hourly = (
        hourly.groupby(
            "date_utc",
            as_index=False,
        )
        .agg(
            era5t_hourly_mean_c=(
                "era5t_global_c",
                "mean",
            ),
            hourly_snapshots=(
                "era5t_global_c",
                "count",
            ),
            hourly_minimum_c=(
                "era5t_global_c",
                "min",
            ),
            hourly_maximum_c=(
                "era5t_global_c",
                "max",
            ),
        )
    )

    matched = hourly[
        hourly["hour_utc"].isin(
            [0, 6, 12, 18]
        )
    ]

    matched_daily = (
        matched.groupby(
            "date_utc",
            as_index=False,
        )
        .agg(
            era5t_matched_6h_c=(
                "era5t_global_c",
                "mean",
            ),
            matched_6h_snapshots=(
                "era5t_global_c",
                "count",
            ),
        )
    )

    daily = full_hourly.merge(
        matched_daily,
        on="date_utc",
        how="left",
    )

    daily["complete_hourly_day"] = (
        daily["hourly_snapshots"] == 24
    )

    daily["complete_matched_6h_day"] = (
        daily["matched_6h_snapshots"] == 4
    )

    daily["sampling_difference_c"] = (
        daily["era5t_matched_6h_c"]
        - daily["era5t_hourly_mean_c"]
    )

    hourly_path = (
        OUTPUT_DIRECTORY
        / "era5t_global_hourly.csv"
    )

    daily_path = (
        OUTPUT_DIRECTORY
        / "era5t_global_daily.csv"
    )

    hourly.to_csv(
        hourly_path,
        index=False,
    )

    daily.to_csv(
        daily_path,
        index=False,
    )

    print("\nERA5T daily whole-Earth temperatures:")
    print(daily.to_string(index=False))

    print("\nCreated:")
    print(hourly_path)
    print(daily_path)


if __name__ == "__main__":
    main()
