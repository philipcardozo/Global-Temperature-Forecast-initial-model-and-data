from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


DATE = "20260728"
CYCLE = "00"


def load_summary(
    path: Path,
    prefix: str,
) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing required file: {path}"
        )

    frame = pd.read_csv(path)

    frame["date"] = pd.to_datetime(
        frame["date_utc"],
        utc=True,
    ).dt.strftime("%Y-%m-%d")

    return frame[
        [
            "date",
            "ensemble_mean_c",
            "ensemble_std_c",
            "p05_c",
            "p95_c",
            "members_available",
        ]
    ].rename(
        columns={
            "ensemble_mean_c":
                f"{prefix}_mean_c",
            "ensemble_std_c":
                f"{prefix}_std_c",
            "p05_c":
                f"{prefix}_p05_c",
            "p95_c":
                f"{prefix}_p95_c",
            "members_available":
                f"{prefix}_members",
        }
    )


def main() -> None:
    gefs = load_summary(
        Path(
            f"output/gefs_{DATE}_{CYCLE}z_"
            "daily_summary.csv"
        ),
        "gefs",
    )

    geps = load_summary(
        Path(
            f"output/geps_{DATE}_{CYCLE}z_"
            "daily_summary.csv"
        ),
        "geps",
    )

    ecmwf = load_summary(
        Path(
            f"output/ecmwf_ens_{DATE}_{CYCLE}z_"
            "daily_summary.csv"
        ),
        "ecmwf",
    )

    comparison = (
        gefs
        .merge(
            geps,
            on="date",
            how="inner",
        )
        .merge(
            ecmwf,
            on="date",
            how="inner",
        )
        .sort_values("date")
        .reset_index(drop=True)
    )

    comparison[
        "geps_minus_gefs_c"
    ] = (
        comparison["geps_mean_c"]
        - comparison["gefs_mean_c"]
    )

    comparison[
        "ecmwf_minus_gefs_c"
    ] = (
        comparison["ecmwf_mean_c"]
        - comparison["gefs_mean_c"]
    )

    comparison[
        "ecmwf_minus_geps_c"
    ] = (
        comparison["ecmwf_mean_c"]
        - comparison["geps_mean_c"]
    )

    mean_columns = [
        "gefs_mean_c",
        "geps_mean_c",
        "ecmwf_mean_c",
    ]

    comparison[
        "equal_system_mean_c"
    ] = comparison[
        mean_columns
    ].mean(axis=1)

    comparison[
        "system_mean_range_c"
    ] = (
        comparison[
            mean_columns
        ].max(axis=1)
        - comparison[
            mean_columns
        ].min(axis=1)
    )

    comparison[
        "warmest_ensemble"
    ] = (
        comparison[mean_columns]
        .idxmax(axis=1)
        .str.replace(
            "_mean_c",
            "",
            regex=False,
        )
    )

    comparison[
        "coolest_ensemble"
    ] = (
        comparison[mean_columns]
        .idxmin(axis=1)
        .str.replace(
            "_mean_c",
            "",
            regex=False,
        )
    )

    common_lower = np.maximum.reduce(
        [
            comparison["gefs_p05_c"],
            comparison["geps_p05_c"],
            comparison["ecmwf_p05_c"],
        ]
    )

    common_upper = np.minimum.reduce(
        [
            comparison["gefs_p95_c"],
            comparison["geps_p95_c"],
            comparison["ecmwf_p95_c"],
        ]
    )

    comparison[
        "three_interval_overlap_c"
    ] = np.maximum(
        0.0,
        common_upper - common_lower,
    )

    comparison[
        "all_three_intervals_overlap"
    ] = (
        comparison[
            "three_interval_overlap_c"
        ] > 0
    )

    output_path = Path(
        f"output/gefs_geps_ecmwf_ens_"
        f"{DATE}_{CYCLE}z.csv"
    )

    comparison.to_csv(
        output_path,
        index=False,
    )

    display_columns = [
        "date",
        "gefs_mean_c",
        "geps_mean_c",
        "ecmwf_mean_c",
        "gefs_std_c",
        "geps_std_c",
        "ecmwf_std_c",
        "ecmwf_minus_gefs_c",
        "ecmwf_minus_geps_c",
        "system_mean_range_c",
        "all_three_intervals_overlap",
        "warmest_ensemble",
        "coolest_ensemble",
    ]

    print(
        "\nGEFS, GEPS and ECMWF ENS"
    )

    print(
        comparison[
            display_columns
        ].to_string(index=False)
    )

    print("\nPeriod diagnostics")

    print(
        "Average ECMWF minus GEFS: "
        f"{comparison['ecmwf_minus_gefs_c'].mean():+.6f} °C"
    )

    print(
        "Average ECMWF minus GEPS: "
        f"{comparison['ecmwf_minus_geps_c'].mean():+.6f} °C"
    )

    print(
        "Average system-mean range: "
        f"{comparison['system_mean_range_c'].mean():.6f} °C"
    )

    print(
        "Dates where all three central "
        "intervals overlap: "
        f"{int(comparison['all_three_intervals_overlap'].sum())}"
        f"/{len(comparison)}"
    )

    print(f"\nCreated: {output_path}")


if __name__ == "__main__":
    main()
