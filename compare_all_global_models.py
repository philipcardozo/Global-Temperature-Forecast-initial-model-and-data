from __future__ import annotations

from pathlib import Path

import pandas as pd


DATE = "20260728"
CYCLE = "00"


def normalize_date(
    frame: pd.DataFrame,
    source_column: str,
) -> pd.DataFrame:
    result = frame.copy()

    result["date"] = pd.to_datetime(
        result[source_column],
        utc=True,
    ).dt.strftime("%Y-%m-%d")

    return result


def require_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"Required file not found: {path}"
        )


def main() -> None:
    gfs_path = Path(
        "output/gfs_global_daily_complete.csv"
    )

    gefs_path = Path(
        f"output/gefs_{DATE}_{CYCLE}z_daily_summary.csv"
    )

    gdps_path = Path(
        f"output/gdps_{DATE}_{CYCLE}z_"
        "global_daily_complete.csv"
    )

    icon_path = Path(
        f"output/icon_{DATE}_{CYCLE}z_"
        "global_daily_complete.csv"
    )

    for path in (
        gfs_path,
        gefs_path,
        gdps_path,
        icon_path,
    ):
        require_file(path)

    # GFS deterministic
    gfs = pd.read_csv(gfs_path)

    gfs = normalize_date(
        gfs,
        "date_utc",
    )[
        [
            "date",
            "global_temperature_c",
        ]
    ].rename(
        columns={
            "global_temperature_c": "gfs_c",
        }
    )

    # GEFS ensemble summary
    gefs = pd.read_csv(gefs_path)

    gefs = normalize_date(
        gefs,
        "date_utc",
    )[
        [
            "date",
            "ensemble_mean_c",
            "ensemble_median_c",
            "ensemble_std_c",
            "p05_c",
            "p95_c",
            "ensemble_min_c",
            "ensemble_max_c",
        ]
    ].rename(
        columns={
            "ensemble_mean_c": "gefs_mean_c",
            "ensemble_median_c": "gefs_median_c",
            "ensemble_std_c": "gefs_std_c",
            "ensemble_min_c": "gefs_min_c",
            "ensemble_max_c": "gefs_max_c",
        }
    )

    # Canadian GDPS deterministic
    gdps = pd.read_csv(gdps_path)

    gdps = normalize_date(
        gdps,
        "date_utc",
    )[
        [
            "date",
            "global_temperature_c",
        ]
    ].rename(
        columns={
            "global_temperature_c": "gdps_c",
        }
    )

    # German ICON deterministic
    icon = pd.read_csv(icon_path)

    icon = normalize_date(
        icon,
        "date_utc",
    )[
        [
            "date",
            "global_temperature_c",
        ]
    ].rename(
        columns={
            "global_temperature_c": "icon_c",
        }
    )

    # Keep only dates available in all four systems.
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
        .merge(
            icon,
            on="date",
            how="inner",
        )
        .sort_values("date")
        .reset_index(drop=True)
    )

    if comparison.empty:
        raise RuntimeError(
            "The four forecast systems have no "
            "overlapping complete dates."
        )

    # Differences relative to GEFS mean.
    comparison["gfs_minus_gefs_mean_c"] = (
        comparison["gfs_c"]
        - comparison["gefs_mean_c"]
    )

    comparison["gdps_minus_gefs_mean_c"] = (
        comparison["gdps_c"]
        - comparison["gefs_mean_c"]
    )

    comparison["icon_minus_gefs_mean_c"] = (
        comparison["icon_c"]
        - comparison["gefs_mean_c"]
    )

    comparison["icon_minus_gfs_c"] = (
        comparison["icon_c"]
        - comparison["gfs_c"]
    )

    comparison["icon_minus_gdps_c"] = (
        comparison["icon_c"]
        - comparison["gdps_c"]
    )

    # Does each deterministic forecast lie inside
    # the central 90% GEFS ensemble interval?
    comparison["gfs_inside_gefs_p05_p95"] = (
        comparison["gfs_c"].between(
            comparison["p05_c"],
            comparison["p95_c"],
        )
    )

    comparison["gdps_inside_gefs_p05_p95"] = (
        comparison["gdps_c"].between(
            comparison["p05_c"],
            comparison["p95_c"],
        )
    )

    comparison["icon_inside_gefs_p05_p95"] = (
        comparison["icon_c"].between(
            comparison["p05_c"],
            comparison["p95_c"],
        )
    )

    model_columns = [
        "gfs_c",
        "gefs_mean_c",
        "gdps_c",
        "icon_c",
    ]

    # Raw multi-system diagnostics.
    # These are not yet bias-corrected forecasts.
    comparison["raw_four_system_mean_c"] = (
        comparison[model_columns].mean(axis=1)
    )

    comparison["raw_four_system_median_c"] = (
        comparison[model_columns].median(axis=1)
    )

    comparison["raw_four_system_min_c"] = (
        comparison[model_columns].min(axis=1)
    )

    comparison["raw_four_system_max_c"] = (
        comparison[model_columns].max(axis=1)
    )

    comparison["raw_four_system_range_c"] = (
        comparison["raw_four_system_max_c"]
        - comparison["raw_four_system_min_c"]
    )

    comparison["raw_four_system_std_c"] = (
        comparison[model_columns].std(
            axis=1,
            ddof=1,
        )
    )

    # Identify warmest and coolest systems.
    comparison["warmest_system"] = (
        comparison[model_columns]
        .idxmax(axis=1)
        .str.replace("_c", "", regex=False)
    )

    comparison["coolest_system"] = (
        comparison[model_columns]
        .idxmin(axis=1)
        .str.replace("_c", "", regex=False)
    )

    output_path = Path(
        f"output/gfs_gefs_gdps_icon_"
        f"{DATE}_{CYCLE}z.csv"
    )

    comparison.to_csv(
        output_path,
        index=False,
    )

    display_columns = [
        "date",
        "gfs_c",
        "gefs_mean_c",
        "gdps_c",
        "icon_c",
        "p05_c",
        "p95_c",
        "icon_minus_gefs_mean_c",
        "icon_minus_gdps_c",
        "gfs_inside_gefs_p05_p95",
        "gdps_inside_gefs_p05_p95",
        "icon_inside_gefs_p05_p95",
        "raw_four_system_range_c",
        "warmest_system",
        "coolest_system",
    ]

    print("\nFour-system comparison")
    print(
        comparison[display_columns].to_string(
            index=False
        )
    )

    print("\nPeriod averages")
    for column in model_columns:
        print(
            f"{column:16s}: "
            f"{comparison[column].mean():.6f} °C"
        )

    print(
        "\nAverage ICON minus GEFS mean: "
        f"{comparison['icon_minus_gefs_mean_c'].mean():+.6f} °C"
    )

    print(
        "Average ICON minus GDPS:      "
        f"{comparison['icon_minus_gdps_c'].mean():+.6f} °C"
    )

    print(
        "Average four-system range:   "
        f"{comparison['raw_four_system_range_c'].mean():.6f} °C"
    )

    print(f"\nCreated: {output_path}")


if __name__ == "__main__":
    main()
