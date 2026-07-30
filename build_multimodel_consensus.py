from __future__ import annotations

from functools import reduce
from pathlib import Path

import numpy as np
import pandas as pd


DATE = "20260728"
CYCLE = "00"

SYSTEMS = {
    "gefs": Path(
        f"output/gefs_{DATE}_{CYCLE}z_"
        "daily_summary.csv"
    ),
    "geps": Path(
        f"output/geps_{DATE}_{CYCLE}z_"
        "daily_summary.csv"
    ),
    "ifs": Path(
        f"output/ecmwf_ens_{DATE}_{CYCLE}z_"
        "daily_summary.csv"
    ),
    "aifs": Path(
        f"output/aifs_ens_{DATE}_{CYCLE}z_"
        "daily_summary.csv"
    ),
}

REQUIRED_COLUMNS = {
    "date_utc",
    "ensemble_mean_c",
    "ensemble_std_c",
    "p05_c",
    "p95_c",
    "members_available",
}


def load_system(
    name: str,
    path: Path,
) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {name.upper()} summary: {path}"
        )

    frame = pd.read_csv(path)

    missing = REQUIRED_COLUMNS.difference(
        frame.columns
    )

    if missing:
        raise KeyError(
            f"{name.upper()} is missing columns: "
            f"{sorted(missing)}"
        )

    frame["date"] = pd.to_datetime(
        frame["date_utc"],
        utc=True,
    ).dt.strftime("%Y-%m-%d")

    frame = frame[
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
                f"{name}_mean_c",
            "ensemble_std_c":
                f"{name}_std_c",
            "p05_c":
                f"{name}_p05_c",
            "p95_c":
                f"{name}_p95_c",
            "members_available":
                f"{name}_members",
        }
    )

    if frame["date"].duplicated().any():
        duplicates = frame.loc[
            frame["date"].duplicated(
                keep=False
            ),
            "date",
        ].tolist()

        raise ValueError(
            f"{name.upper()} contains duplicate "
            f"dates: {duplicates}"
        )

    return frame


def main() -> None:
    frames = [
        load_system(name, path)
        for name, path in SYSTEMS.items()
    ]

    comparison = reduce(
        lambda left, right: left.merge(
            right,
            on="date",
            how="inner",
            validate="one_to_one",
        ),
        frames,
    )

    comparison = (
        comparison
        .sort_values("date")
        .reset_index(drop=True)
    )

    if comparison.empty:
        raise RuntimeError(
            "No common dates exist across "
            "the four ensemble systems."
        )

    system_names = list(
        SYSTEMS.keys()
    )

    mean_columns = [
        f"{name}_mean_c"
        for name in system_names
    ]

    std_columns = [
        f"{name}_std_c"
        for name in system_names
    ]

    p05_columns = [
        f"{name}_p05_c"
        for name in system_names
    ]

    p95_columns = [
        f"{name}_p95_c"
        for name in system_names
    ]

    # Equal weight for each forecasting system.
    comparison["equal_center_mean_c"] = (
        comparison[mean_columns].mean(axis=1)
    )

    comparison["equal_center_median_c"] = (
        comparison[mean_columns].median(axis=1)
    )

    # Physics-based center consensus.
    physics_columns = [
        "gefs_mean_c",
        "geps_mean_c",
        "ifs_mean_c",
    ]

    comparison["physics_consensus_mean_c"] = (
        comparison[
            physics_columns
        ].mean(axis=1)
    )

    # AI architecture diagnostics.
    comparison["aifs_minus_ifs_c"] = (
        comparison["aifs_mean_c"]
        - comparison["ifs_mean_c"]
    )

    comparison[
        "aifs_minus_physics_consensus_c"
    ] = (
        comparison["aifs_mean_c"]
        - comparison[
            "physics_consensus_mean_c"
        ]
    )

    # Between-center structural disagreement.
    comparison["center_mean_min_c"] = (
        comparison[mean_columns].min(axis=1)
    )

    comparison["center_mean_max_c"] = (
        comparison[mean_columns].max(axis=1)
    )

    comparison["center_mean_range_c"] = (
        comparison["center_mean_max_c"]
        - comparison["center_mean_min_c"]
    )

    comparison["between_center_std_c"] = (
        comparison[mean_columns].std(
            axis=1,
            ddof=1,
        )
    )

    comparison["warmest_system"] = (
        comparison[mean_columns]
        .idxmax(axis=1)
        .str.replace(
            "_mean_c",
            "",
            regex=False,
        )
    )

    comparison["coolest_system"] = (
        comparison[mean_columns]
        .idxmin(axis=1)
        .str.replace(
            "_mean_c",
            "",
            regex=False,
        )
    )

    # Average internal ensemble variance.
    within_variance = (
        comparison[std_columns]
        .pow(2)
        .mean(axis=1)
    )

    comparison["within_center_rms_spread_c"] = (
        np.sqrt(within_variance)
    )

    # Population variance of the four center means.
    between_variance = (
        comparison[mean_columns]
        .var(
            axis=1,
            ddof=0,
        )
    )

    # Law of total variance for an equal-weight
    # mixture of the four ensemble systems.
    total_variance = (
        within_variance
        + between_variance
    )

    comparison[
        "multimodel_total_spread_c"
    ] = np.sqrt(total_variance)

    comparison[
        "structural_variance_fraction"
    ] = (
        between_variance
        / total_variance.replace(
            0,
            np.nan,
        )
    )

    # Normal approximation to the equal-center
    # mixture. These are diagnostics, not yet
    # calibrated probabilities.
    z_95 = 1.6448536269514722

    comparison[
        "normal_approx_multimodel_p05_c"
    ] = (
        comparison["equal_center_mean_c"]
        - z_95
        * comparison[
            "multimodel_total_spread_c"
        ]
    )

    comparison[
        "normal_approx_multimodel_p95_c"
    ] = (
        comparison["equal_center_mean_c"]
        + z_95
        * comparison[
            "multimodel_total_spread_c"
        ]
    )

    # Intersection of the four reported
    # central 90% intervals.
    common_lower = (
        comparison[p05_columns].max(axis=1)
    )

    common_upper = (
        comparison[p95_columns].min(axis=1)
    )

    comparison[
        "common_interval_lower_c"
    ] = common_lower

    comparison[
        "common_interval_upper_c"
    ] = common_upper

    comparison[
        "common_central90_overlap_c"
    ] = (
        common_upper - common_lower
    ).clip(lower=0)

    comparison[
        "all_four_central_intervals_overlap"
    ] = (
        comparison[
            "common_central90_overlap_c"
        ] > 0
    )

    # Union of all four central intervals.
    comparison["union_p05_c"] = (
        comparison[p05_columns].min(axis=1)
    )

    comparison["union_p95_c"] = (
        comparison[p95_columns].max(axis=1)
    )

    comparison[
        "central90_union_width_c"
    ] = (
        comparison["union_p95_c"]
        - comparison["union_p05_c"]
    )

    comparison[
        "common_to_union_overlap_fraction"
    ] = (
        comparison[
            "common_central90_overlap_c"
        ]
        / comparison[
            "central90_union_width_c"
        ].replace(0, np.nan)
    )

    # Rank dates from greatest to least
    # disagreement.
    comparison[
        "disagreement_rank"
    ] = (
        comparison[
            "center_mean_range_c"
        ]
        .rank(
            ascending=False,
            method="dense",
        )
        .astype(int)
    )

    output_path = Path(
        f"output/multimodel_consensus_"
        f"{DATE}_{CYCLE}z.csv"
    )

    json_path = Path(
        f"output/multimodel_consensus_"
        f"{DATE}_{CYCLE}z.json"
    )

    comparison.to_csv(
        output_path,
        index=False,
    )

    json_path.write_text(
        comparison.to_json(
            orient="records",
            indent=2,
        ),
        encoding="utf-8",
    )

    display_columns = [
        "date",
        "gefs_mean_c",
        "geps_mean_c",
        "ifs_mean_c",
        "aifs_mean_c",
        "equal_center_mean_c",
        "physics_consensus_mean_c",
        "aifs_minus_ifs_c",
        "aifs_minus_physics_consensus_c",
        "center_mean_range_c",
        "within_center_rms_spread_c",
        "multimodel_total_spread_c",
        "structural_variance_fraction",
        "all_four_central_intervals_overlap",
        "warmest_system",
        "coolest_system",
        "disagreement_rank",
    ]

    print(
        "\nMultimodel consensus and "
        "structural disagreement"
    )

    print(
        comparison[
            display_columns
        ].to_string(index=False)
    )

    print("\nPeriod diagnostics")

    print(
        "Equal-center mean:              "
        f"{comparison['equal_center_mean_c'].mean():.6f} °C"
    )

    print(
        "Physics consensus mean:         "
        f"{comparison['physics_consensus_mean_c'].mean():.6f} °C"
    )

    print(
        "Average AIFS minus IFS:         "
        f"{comparison['aifs_minus_ifs_c'].mean():+.6f} °C"
    )

    print(
        "Average AIFS minus physics:     "
        f"{comparison['aifs_minus_physics_consensus_c'].mean():+.6f} °C"
    )

    print(
        "Average center-mean range:      "
        f"{comparison['center_mean_range_c'].mean():.6f} °C"
    )

    print(
        "Average internal RMS spread:   "
        f"{comparison['within_center_rms_spread_c'].mean():.6f} °C"
    )

    print(
        "Average total mixture spread:  "
        f"{comparison['multimodel_total_spread_c'].mean():.6f} °C"
    )

    print(
        "Average structural fraction:  "
        f"{comparison['structural_variance_fraction'].mean():.2%}"
    )

    overlap_count = int(
        comparison[
            "all_four_central_intervals_overlap"
        ].sum()
    )

    print(
        "Common central-90% overlap:     "
        f"{overlap_count}/{len(comparison)} dates"
    )

    highest = comparison.loc[
        comparison[
            "center_mean_range_c"
        ].idxmax()
    ]

    print(
        "Greatest disagreement date:    "
        f"{highest['date']} "
        f"({highest['center_mean_range_c']:.6f} °C)"
    )

    print("\nCreated:")
    print(output_path)
    print(json_path)


if __name__ == "__main__":
    main()
