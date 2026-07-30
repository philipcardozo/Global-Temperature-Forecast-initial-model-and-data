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


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--init-date",
        default="20260728",
    )

    parser.add_argument(
        "--cycle",
        default="00",
        choices=("00", "12"),
    )

    args = parser.parse_args()

    prefix = (
        f"{args.init_date}_"
        f"{args.cycle}z"
    )

    consensus_path = Path(
        f"output/multimodel_consensus_"
        f"{prefix}.csv"
    )

    era5t_path = Path(
        "output/era5t_global_daily.csv"
    )

    for path in (
        consensus_path,
        era5t_path,
    ):
        if not path.exists():
            raise FileNotFoundError(
                f"Missing required file: {path}"
            )

    consensus = pd.read_csv(
        consensus_path
    )

    consensus["date_utc"] = (
        pd.to_datetime(
            consensus["date"],
            utc=True,
        ).dt.floor("D")
    )

    era5t = pd.read_csv(
        era5t_path
    )

    era5t["date_utc"] = (
        pd.to_datetime(
            era5t["date_utc"],
            utc=True,
        ).dt.floor("D")
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

    verification = consensus.merge(
        actual,
        on="date_utc",
        how="inner",
    )

    verification[
        "actual_minus_equal_center_c"
    ] = (
        verification[
            "era5t_matched_6h_c"
        ]
        - verification[
            "equal_center_mean_c"
        ]
    )

    verification[
        "equal_center_absolute_error_c"
    ] = verification[
        "actual_minus_equal_center_c"
    ].abs()

    verification[
        "actual_inside_multimodel_normal_p05_p95"
    ] = verification[
        "era5t_matched_6h_c"
    ].between(
        verification[
            "normal_approx_multimodel_p05_c"
        ],
        verification[
            "normal_approx_multimodel_p95_c"
        ],
    )

    verification[
        "actual_inside_center_interval_union"
    ] = verification[
        "era5t_matched_6h_c"
    ].between(
        verification["union_p05_c"],
        verification["union_p95_c"],
    )

    output_path = Path(
        f"output/verification/"
        f"multimodel_consensus_"
        f"{prefix}_vs_era5t.csv"
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
        "Multimodel verified days:",
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
            "equal_center_mean_c",
            "era5t_matched_6h_c",
            "actual_minus_equal_center_c",
            "equal_center_absolute_error_c",
            "actual_inside_multimodel_normal_p05_p95",
            "actual_inside_center_interval_union",
        ]

        print(
            verification[
                columns
            ].to_string(index=False)
        )

        mean_error = verification[
            "actual_minus_equal_center_c"
        ].mean()

        mae = verification[
            "equal_center_absolute_error_c"
        ].mean()

        rmse = (
            verification[
                "actual_minus_equal_center_c"
            ]
            .pow(2)
            .mean()
            ** 0.5
        )

        print("\nConsensus metrics")
        print(
            f"Mean error:          "
            f"{mean_error:+.6f} °C"
        )
        print(
            f"Mean absolute error: "
            f"{mae:.6f} °C"
        )
        print(
            f"RMSE:                "
            f"{rmse:.6f} °C"
        )

    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()
