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
) -> pd.DataFrame:
    result = frame.copy()

    result["date_utc"] = pd.to_datetime(
        result["date_utc"],
        utc=True,
    ).dt.floor("D")

    return result


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

    era5t_path = Path(
        "output/era5t_global_daily.csv"
    )

    summary_path = Path(
        f"output/geps_{prefix}_"
        "daily_summary.csv"
    )

    members_path = Path(
        f"output/geps_{prefix}_"
        "global_daily_members.csv"
    )

    for path in (
        era5t_path,
        summary_path,
        members_path,
    ):
        if not path.exists():
            raise FileNotFoundError(
                f"Missing required file: {path}"
            )

    era5t = normalize_date(
        pd.read_csv(
            era5t_path
        )
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

    summary = normalize_date(
        pd.read_csv(
            summary_path
        )
    )

    verification = summary.merge(
        actual,
        on="date_utc",
        how="inner",
    )

    verification[
        "actual_minus_geps_mean_c"
    ] = (
        verification[
            "era5t_matched_6h_c"
        ]
        - verification[
            "ensemble_mean_c"
        ]
    )

    verification[
        "geps_mean_absolute_error_c"
    ] = verification[
        "actual_minus_geps_mean_c"
    ].abs()

    verification[
        "geps_mean_squared_error_c2"
    ] = (
        verification[
            "actual_minus_geps_mean_c"
        ] ** 2
    )

    verification[
        "actual_inside_p05_p95"
    ] = verification[
        "era5t_matched_6h_c"
    ].between(
        verification["p05_c"],
        verification["p95_c"],
    )

    verification[
        "actual_inside_min_max"
    ] = verification[
        "era5t_matched_6h_c"
    ].between(
        verification[
            "ensemble_min_c"
        ],
        verification[
            "ensemble_max_c"
        ],
    )

    members = normalize_date(
        pd.read_csv(
            members_path
        )
    )

    members = members[
        true_flag(
            members[
                "complete_day"
            ]
        )
    ].copy()

    member_errors = members.merge(
        actual,
        on="date_utc",
        how="inner",
    )

    member_errors[
        "actual_minus_member_c"
    ] = (
        member_errors[
            "era5t_matched_6h_c"
        ]
        - member_errors[
            "global_temperature_c"
        ]
    )

    member_errors[
        "member_absolute_error_c"
    ] = member_errors[
        "actual_minus_member_c"
    ].abs()

    output_directory = Path(
        "output/verification"
    )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    summary_output = (
        output_directory
        / f"geps_{prefix}_vs_era5t.csv"
    )

    members_output = (
        output_directory
        / f"geps_{prefix}_"
        "member_errors.csv"
    )

    verification.to_csv(
        summary_output,
        index=False,
    )

    member_errors.to_csv(
        members_output,
        index=False,
    )

    print(
        "GEPS verified days:",
        len(verification),
    )

    print(
        "GEPS member-error rows:",
        len(member_errors),
    )

    if verification.empty:
        print(
            "No overlapping complete ERA5T "
            "dates are available yet."
        )
    else:
        columns = [
            "date_utc",
            "ensemble_mean_c",
            "p05_c",
            "p95_c",
            "era5t_matched_6h_c",
            "actual_minus_geps_mean_c",
            "geps_mean_absolute_error_c",
            "actual_inside_p05_p95",
            "actual_inside_min_max",
        ]

        print(
            verification[
                columns
            ].to_string(index=False)
        )

        mean_error = verification[
            "actual_minus_geps_mean_c"
        ].mean()

        mean_absolute_error = (
            verification[
                "geps_mean_absolute_error_c"
            ].mean()
        )

        rmse = (
            verification[
                "geps_mean_squared_error_c2"
            ].mean() ** 0.5
        )

        print("\nGEPS metrics")
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
            f"{rmse:.6f} °C"
        )

    print("\nCreated:")
    print(summary_output)
    print(members_output)


if __name__ == "__main__":
    main()
