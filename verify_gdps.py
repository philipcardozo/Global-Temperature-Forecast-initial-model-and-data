from __future__ import annotations

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
    era5t = pd.read_csv(
        "output/era5t_global_daily.csv"
    )

    era5t = normalize_date(
        era5t,
        "date_utc",
    )

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

    gdps = pd.read_csv(
        "output/"
        "gdps_20260728_00z_"
        "global_daily_complete.csv"
    )

    gdps = normalize_date(
        gdps,
        "date_utc",
    )

    verification = gdps.merge(
        actual,
        on="date_utc",
        how="inner",
    )

    if not verification.empty:
        verification[
            "actual_minus_gdps_c"
        ] = (
            verification[
                "era5t_matched_6h_c"
            ]
            - verification[
                "global_temperature_c"
            ]
        )

        verification[
            "gdps_absolute_error_c"
        ] = verification[
            "actual_minus_gdps_c"
        ].abs()

    output_path = Path(
        "output/verification/"
        "gdps_20260728_00z_vs_era5t.csv"
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    verification.to_csv(
        output_path,
        index=False,
    )

    print(
        "GDPS verified days:",
        len(verification),
    )

    if verification.empty:
        print(
            "No overlapping complete ERA5T "
            "dates are available yet."
        )
    else:
        columns = [
            "date_utc",
            "global_temperature_c",
            "era5t_matched_6h_c",
            "actual_minus_gdps_c",
            "gdps_absolute_error_c",
        ]

        print(
            verification[
                columns
            ].to_string(index=False)
        )

    print(
        f"Created: {output_path}"
    )


if __name__ == "__main__":
    main()
