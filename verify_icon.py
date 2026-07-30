from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def true_flag(
    series: pd.Series,
) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .eq("true")
    )


def normalize_date(
    frame: pd.DataFrame,
    column: str,
) -> pd.DataFrame:
    result = frame.copy()

    result["date_utc"] = pd.to_datetime(
        result[column],
        utc=True,
    ).dt.floor("D")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Verify ICON global-temperature forecasts "
            "against complete ERA5T daily fields."
        )
    )

    parser.add_argument(
        "--init-date",
        default="20260728",
    )

    parser.add_argument(
        "--cycle",
        default="00",
        choices=("00", "06", "12", "18"),
    )

    args = parser.parse_args()

    prefix = (
        f"{args.init_date}_{args.cycle}z"
    )

    era5t_path = Path(
        "output/era5t_global_daily.csv"
    )

    icon_path = Path(
        f"output/icon_{prefix}_"
        "global_daily_complete.csv"
    )

    if not era5t_path.exists():
        raise FileNotFoundError(
            f"Missing ERA5T file: {era5t_path}"
        )

    if not icon_path.exists():
        raise FileNotFoundError(
            f"Missing ICON file: {icon_path}"
        )

    era5t = pd.read_csv(
        era5t_path
    )

    era5t = normalize_date(
        era5t,
        "date_utc",
    )

    # Use only complete 00/06/12/18 ERA5T days
    # for sampling-compatible verification.
    era5t = era5t[
        true_flag(
            era5t[
                "complete_matched_6h_day"
            ]
        )
    ].copy()

    actual = era5t[
        [
            "date_utc",
            "era5t_hourly_mean_c",
            "era5t_matched_6h_c",
            "sampling_difference_c",
        ]
    ]

    icon = pd.read_csv(
        icon_path
    )

    icon = normalize_date(
        icon,
        "date_utc",
    )

    verification = icon.merge(
        actual,
        on="date_utc",
        how="inner",
    )

    # Create these columns even when there are
    # currently zero overlapping dates.
    verification["actual_minus_icon_c"] = (
        verification["era5t_matched_6h_c"]
        - verification["global_temperature_c"]
    )

    verification["icon_absolute_error_c"] = (
        verification["actual_minus_icon_c"].abs()
    )

    verification["icon_squared_error_c2"] = (
        verification["actual_minus_icon_c"] ** 2
    )

    output_directory = Path(
        "output/verification"
    )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_directory
        / f"icon_{prefix}_vs_era5t.csv"
    )

    verification.to_csv(
        output_path,
        index=False,
    )

    print(
        "ICON verified days:",
        len(verification),
    )

    if verification.empty:
        print(
            "No overlapping complete ERA5T "
            "dates are available yet."
        )
    else:
        display_columns = [
            "date_utc",
            "global_temperature_c",
            "era5t_matched_6h_c",
            "actual_minus_icon_c",
            "icon_absolute_error_c",
        ]

        print(
            verification[
                display_columns
            ].to_string(index=False)
        )

        mean_error = (
            verification[
                "actual_minus_icon_c"
            ].mean()
        )

        mean_absolute_error = (
            verification[
                "icon_absolute_error_c"
            ].mean()
        )

        root_mean_squared_error = (
            verification[
                "icon_squared_error_c2"
            ].mean() ** 0.5
        )

        print("\nICON verification metrics")
        print(
            f"Mean error:          "
            f"{mean_error:+.6f} °C"
        )
        print(
            f"Mean absolute error: "
            f"{mean_absolute_error:.6f} °C"
        )
        print(
            f"RMSE:                "
            f"{root_mean_squared_error:.6f} °C"
        )

    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()
