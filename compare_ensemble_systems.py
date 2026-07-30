from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


DATE = "20260728"
CYCLE = "00"


def normalize_date(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    result = frame.copy()

    result["date"] = pd.to_datetime(
        result["date_utc"],
        utc=True,
    ).dt.strftime("%Y-%m-%d")

    return result


def main() -> None:
    gefs_path = Path(
        f"output/gefs_{DATE}_{CYCLE}z_"
        "daily_summary.csv"
    )

    geps_path = Path(
        f"output/geps_{DATE}_{CYCLE}z_"
        "daily_summary.csv"
    )

    for path in (
        gefs_path,
        geps_path,
    ):
        if not path.exists():
            raise FileNotFoundError(
                f"Missing required file: {path}"
            )

    gefs = normalize_date(
        pd.read_csv(
            gefs_path
        )
    )

    gefs = gefs[
        [
            "date",
            "ensemble_mean_c",
            "ensemble_median_c",
            "ensemble_std_c",
            "p05_c",
            "p95_c",
            "ensemble_min_c",
            "ensemble_max_c",
            "control_c",
            "members_available",
        ]
    ].rename(
        columns={
            "ensemble_mean_c":
                "gefs_mean_c",
            "ensemble_median_c":
                "gefs_median_c",
            "ensemble_std_c":
                "gefs_std_c",
            "p05_c":
                "gefs_p05_c",
            "p95_c":
                "gefs_p95_c",
            "ensemble_min_c":
                "gefs_min_c",
            "ensemble_max_c":
                "gefs_max_c",
            "control_c":
                "gefs_control_c",
            "members_available":
                "gefs_members",
        }
    )

    geps = normalize_date(
        pd.read_csv(
            geps_path
        )
    )

    geps = geps[
        [
            "date",
            "ensemble_mean_c",
            "ensemble_median_c",
            "ensemble_std_c",
            "p05_c",
            "p95_c",
            "ensemble_min_c",
            "ensemble_max_c",
            "control_c",
            "members_available",
        ]
    ].rename(
        columns={
            "ensemble_mean_c":
                "geps_mean_c",
            "ensemble_median_c":
                "geps_median_c",
            "ensemble_std_c":
                "geps_std_c",
            "p05_c":
                "geps_p05_c",
            "p95_c":
                "geps_p95_c",
            "ensemble_min_c":
                "geps_min_c",
            "ensemble_max_c":
                "geps_max_c",
            "control_c":
                "geps_control_c",
            "members_available":
                "geps_members",
        }
    )

    comparison = (
        gefs
        .merge(
            geps,
            on="date",
            how="inner",
        )
        .sort_values("date")
        .reset_index(drop=True)
    )

    comparison[
        "geps_minus_gefs_mean_c"
    ] = (
        comparison["geps_mean_c"]
        - comparison["gefs_mean_c"]
    )

    comparison[
        "absolute_mean_difference_c"
    ] = comparison[
        "geps_minus_gefs_mean_c"
    ].abs()

    comparison[
        "pooled_ensemble_spread_c"
    ] = np.sqrt(
        comparison["gefs_std_c"] ** 2
        + comparison["geps_std_c"] ** 2
    )

    comparison[
        "standardized_mean_difference"
    ] = (
        comparison[
            "geps_minus_gefs_mean_c"
        ]
        / comparison[
            "pooled_ensemble_spread_c"
        ].replace(0, np.nan)
    )

    lower_overlap = np.maximum(
        comparison["gefs_p05_c"],
        comparison["geps_p05_c"],
    )

    upper_overlap = np.minimum(
        comparison["gefs_p95_c"],
        comparison["geps_p95_c"],
    )

    comparison[
        "p05_p95_overlap_c"
    ] = np.maximum(
        0.0,
        upper_overlap
        - lower_overlap,
    )

    union_lower = np.minimum(
        comparison["gefs_p05_c"],
        comparison["geps_p05_c"],
    )

    union_upper = np.maximum(
        comparison["gefs_p95_c"],
        comparison["geps_p95_c"],
    )

    comparison[
        "p05_p95_union_c"
    ] = (
        union_upper
        - union_lower
    )

    comparison[
        "p05_p95_overlap_fraction"
    ] = (
        comparison[
            "p05_p95_overlap_c"
        ]
        / comparison[
            "p05_p95_union_c"
        ].replace(0, np.nan)
    )

    comparison[
        "central_intervals_overlap"
    ] = (
        comparison[
            "p05_p95_overlap_c"
        ] > 0
    )

    comparison[
        "combined_ensemble_mean_c"
    ] = (
        (
            comparison["gefs_mean_c"]
            * comparison["gefs_members"]
        )
        + (
            comparison["geps_mean_c"]
            * comparison["geps_members"]
        )
    ) / (
        comparison["gefs_members"]
        + comparison["geps_members"]
    )

    output_path = Path(
        f"output/gefs_vs_geps_"
        f"{DATE}_{CYCLE}z.csv"
    )

    comparison.to_csv(
        output_path,
        index=False,
    )

    columns = [
        "date",
        "gefs_mean_c",
        "geps_mean_c",
        "geps_minus_gefs_mean_c",
        "gefs_std_c",
        "geps_std_c",
        "gefs_p05_c",
        "gefs_p95_c",
        "geps_p05_c",
        "geps_p95_c",
        "central_intervals_overlap",
        "p05_p95_overlap_fraction",
        "standardized_mean_difference",
        "combined_ensemble_mean_c",
    ]

    print(
        "\nGEFS versus GEPS"
    )

    print(
        comparison[
            columns
        ].to_string(index=False)
    )

    print(
        "\nPeriod diagnostics"
    )

    print(
        "Average GEPS minus GEFS mean: "
        f"{comparison['geps_minus_gefs_mean_c'].mean():+.6f} °C"
    )

    print(
        "Average absolute mean difference: "
        f"{comparison['absolute_mean_difference_c'].mean():.6f} °C"
    )

    print(
        "Dates with overlapping central intervals: "
        f"{int(comparison['central_intervals_overlap'].sum())}"
        f"/{len(comparison)}"
    )

    print(
        f"\nCreated: {output_path}"
    )


if __name__ == "__main__":
    main()
