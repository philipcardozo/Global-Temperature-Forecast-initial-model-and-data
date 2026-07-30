from __future__ import annotations

from pathlib import Path

import pandas as pd


INITIALIZATION_DATE = "20260728"
CYCLE = "00"


def normalized_date(
    frame: pd.DataFrame,
    column: str,
) -> pd.DataFrame:
    result = frame.copy()

    result["date"] = pd.to_datetime(
        result[column],
        utc=True,
    ).dt.strftime("%Y-%m-%d")

    return result


def locate_gfs_file() -> Path:
    candidates = [
        Path(
            "output/"
            "gfs_global_daily_complete.csv"
        ),
        Path(
            "output/"
            "gfs_20260728_00z_global_daily.csv"
        ),
    ]

    for path in candidates:
        if path.exists():
            return path

    matches = sorted(
        Path("output").glob(
            "gfs*global_daily*.csv"
        )
    )

    if not matches:
        raise FileNotFoundError(
            "No GFS daily file found."
        )

    return matches[0]


def true_flag(
    series: pd.Series,
) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .eq("true")
    )


def main() -> None:
    gfs_path = locate_gfs_file()

    print(
        f"Using GFS file: {gfs_path}"
    )

    gfs = pd.read_csv(
        gfs_path
    )

    if (
        "complete_day"
        in gfs.columns
    ):
        gfs = gfs[
            true_flag(
                gfs["complete_day"]
            )
        ].copy()

    gfs = normalized_date(
        gfs,
        "date_utc",
    )

    gfs = gfs[
        [
            "date",
            "global_temperature_c",
        ]
    ].rename(
        columns={
            "global_temperature_c":
            "gfs_c"
        }
    )

    gefs = pd.read_csv(
        "output/"
        "gefs_20260728_00z_daily_summary.csv"
    )

    gefs = normalized_date(
        gefs,
        "date_utc",
    )

    gefs = gefs[
        [
            "date",
            "ensemble_mean_c",
            "ensemble_median_c",
            "p05_c",
            "p95_c",
            "ensemble_min_c",
            "ensemble_max_c",
            "ensemble_std_c",
        ]
    ].rename(
        columns={
            "ensemble_mean_c":
            "gefs_mean_c",
            "ensemble_median_c":
            "gefs_median_c",
            "ensemble_min_c":
            "gefs_min_c",
            "ensemble_max_c":
            "gefs_max_c",
            "ensemble_std_c":
            "gefs_std_c",
        }
    )

    gdps = pd.read_csv(
        "output/"
        "gdps_20260728_00z_"
        "global_daily_complete.csv"
    )

    gdps = normalized_date(
        gdps,
        "date_utc",
    )

    gdps = gdps[
        [
            "date",
            "global_temperature_c",
        ]
    ].rename(
        columns={
            "global_temperature_c":
            "gdps_c"
        }
    )

    comparison = (
        gfs
        .merge(
            gefs,
            on="date",
            how="inner",
        )
        .merge(
            gdps,
            on="date",
            how="inner",
        )
    )

    comparison[
        "gfs_minus_gefs_mean_c"
    ] = (
        comparison["gfs_c"]
        - comparison["gefs_mean_c"]
    )

    comparison[
        "gdps_minus_gefs_mean_c"
    ] = (
        comparison["gdps_c"]
        - comparison["gefs_mean_c"]
    )

    comparison[
        "gdps_minus_gfs_c"
    ] = (
        comparison["gdps_c"]
        - comparison["gfs_c"]
    )

    comparison[
        "gdps_inside_gefs_p05_p95"
    ] = comparison[
        "gdps_c"
    ].between(
        comparison["p05_c"],
        comparison["p95_c"],
    )

    comparison[
        "three_model_mean_c"
    ] = comparison[
        [
            "gfs_c",
            "gefs_mean_c",
            "gdps_c",
        ]
    ].mean(axis=1)

    comparison[
        "three_model_std_c"
    ] = comparison[
        [
            "gfs_c",
            "gefs_mean_c",
            "gdps_c",
        ]
    ].std(
        axis=1,
        ddof=1,
    )

    output_path = Path(
        "output/"
        "gfs_gefs_gdps_"
        "20260728_00z.csv"
    )

    comparison.to_csv(
        output_path,
        index=False,
    )

    columns = [
        "date",
        "gfs_c",
        "gefs_mean_c",
        "gdps_c",
        "p05_c",
        "p95_c",
        "gfs_minus_gefs_mean_c",
        "gdps_minus_gefs_mean_c",
        "gdps_minus_gfs_c",
        "gdps_inside_gefs_p05_p95",
        "three_model_std_c",
    ]

    print(
        comparison[
            columns
        ].to_string(index=False)
    )

    print(
        f"\nCreated: {output_path}"
    )


if __name__ == "__main__":
    main()
