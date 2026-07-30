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

    era5t = normalize_date(
        pd.read_csv(
            "output/era5t_global_daily.csv"
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
            f"output/ecmwf_ens_{prefix}_"
            "daily_summary.csv"
        )
    )

    members = normalize_date(
        pd.read_csv(
            f"output/ecmwf_ens_{prefix}_"
            "global_daily_members.csv"
        )
    )

    verification = summary.merge(
        actual,
        on="date_utc",
        how="inner",
    )

    verification[
        "actual_minus_ecmwf_mean_c"
    ] = (
        verification[
            "era5t_matched_6h_c"
        ]
        - verification[
            "ensemble_mean_c"
        ]
    )

    verification[
        "ecmwf_mean_absolute_error_c"
    ] = verification[
        "actual_minus_ecmwf_mean_c"
    ].abs()

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
        verification["ensemble_min_c"],
        verification["ensemble_max_c"],
    )

    members = members[
        true_flag(
            members["complete_day"]
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
        / (
            f"ecmwf_ens_{prefix}_"
            "vs_era5t.csv"
        )
    )

    members_output = (
        output_directory
        / (
            f"ecmwf_ens_{prefix}_"
            "member_errors.csv"
        )
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
        "ECMWF ENS verified days:",
        len(verification),
    )

    print(
        "ECMWF member-error rows:",
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
            "actual_minus_ecmwf_mean_c",
            "ecmwf_mean_absolute_error_c",
            "actual_inside_p05_p95",
            "actual_inside_min_max",
        ]

        print(
            verification[
                columns
            ].to_string(index=False)
        )

    print("\nCreated:")
    print(summary_output)
    print(members_output)


if __name__ == "__main__":
    main()
