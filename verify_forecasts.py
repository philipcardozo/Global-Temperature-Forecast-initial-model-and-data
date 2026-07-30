from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def normalize_date(
    frame: pd.DataFrame,
    source_column: str,
) -> pd.DataFrame:
    result = frame.copy()

    result["date_utc"] = pd.to_datetime(
        result[source_column],
        utc=True,
    ).dt.floor("D")

    return result


def read_complete_flag(
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
        choices=("00", "06", "12", "18"),
    )

    args = parser.parse_args()

    output_directory = (
        Path("output")
        / "verification"
    )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    era5t = pd.read_csv(
        "output/era5t_global_daily.csv"
    )

    era5t = normalize_date(
        era5t,
        "date_utc",
    )

    era5t = era5t[
        read_complete_flag(
            era5t["complete_matched_6h_day"]
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

    prefix = (
        f"{args.init_date}_{args.cycle}z"
    )

    # -----------------------------------------
    # Deterministic GFS verification
    # -----------------------------------------

    gfs = pd.read_csv(
        "output/gfs_global_daily_complete.csv"
    )

    gfs = normalize_date(
        gfs,
        "date_utc",
    )

    gfs_verification = gfs.merge(
        actual,
        on="date_utc",
        how="inner",
    )

    if not gfs_verification.empty:
        gfs_verification[
            "actual_minus_gfs_c"
        ] = (
            gfs_verification[
                "era5t_matched_6h_c"
            ]
            - gfs_verification[
                "global_temperature_c"
            ]
        )

        gfs_verification[
            "gfs_absolute_error_c"
        ] = (
            gfs_verification[
                "actual_minus_gfs_c"
            ].abs()
        )

    gfs_path = (
        output_directory
        / f"gfs_{prefix}_vs_era5t.csv"
    )

    gfs_verification.to_csv(
        gfs_path,
        index=False,
    )

    # -----------------------------------------
    # GEFS ensemble-summary verification
    # -----------------------------------------

    gefs_summary = pd.read_csv(
        f"output/gefs_{prefix}_daily_summary.csv"
    )

    gefs_summary = normalize_date(
        gefs_summary,
        "date_utc",
    )

    gefs_verification = gefs_summary.merge(
        actual,
        on="date_utc",
        how="inner",
    )

    if not gefs_verification.empty:
        gefs_verification[
            "actual_minus_gefs_mean_c"
        ] = (
            gefs_verification[
                "era5t_matched_6h_c"
            ]
            - gefs_verification[
                "ensemble_mean_c"
            ]
        )

        gefs_verification[
            "gefs_mean_absolute_error_c"
        ] = (
            gefs_verification[
                "actual_minus_gefs_mean_c"
            ].abs()
        )

        gefs_verification[
            "actual_inside_p05_p95"
        ] = (
            gefs_verification[
                "era5t_matched_6h_c"
            ].between(
                gefs_verification["p05_c"],
                gefs_verification["p95_c"],
            )
        )

        gefs_verification[
            "actual_inside_min_max"
        ] = (
            gefs_verification[
                "era5t_matched_6h_c"
            ].between(
                gefs_verification[
                    "ensemble_min_c"
                ],
                gefs_verification[
                    "ensemble_max_c"
                ],
            )
        )

    gefs_path = (
        output_directory
        / f"gefs_{prefix}_vs_era5t.csv"
    )

    gefs_verification.to_csv(
        gefs_path,
        index=False,
    )

    # -----------------------------------------
    # Every GEFS member versus ERA5T
    # -----------------------------------------

    members = pd.read_csv(
        f"output/"
        f"gefs_{prefix}_global_daily_members.csv"
    )

    members = normalize_date(
        members,
        "date_utc",
    )

    members = members[
        read_complete_flag(
            members["complete_day"]
        )
    ].copy()

    member_errors = members.merge(
        actual,
        on="date_utc",
        how="inner",
    )

    if not member_errors.empty:
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
        ] = (
            member_errors[
                "actual_minus_member_c"
            ].abs()
        )

    member_path = (
        output_directory
        / f"gefs_{prefix}_member_errors.csv"
    )

    member_errors.to_csv(
        member_path,
        index=False,
    )

    print("\nVerification availability")
    print(
        f"GFS verified days:  "
        f"{len(gfs_verification)}"
    )
    print(
        f"GEFS verified days: "
        f"{len(gefs_verification)}"
    )
    print(
        f"Member-error rows:  "
        f"{len(member_errors)}"
    )

    if gfs_verification.empty:
        print(
            "\nNo overlapping realized ERA5T dates yet."
        )
        print(
            "This is expected until ERA5T reaches "
            "the forecast dates."
        )
    else:
        print("\nGFS verification:")
        print(
            gfs_verification.to_string(
                index=False
            )
        )

    if not gefs_verification.empty:
        print("\nGEFS verification:")
        print(
            gefs_verification.to_string(
                index=False
            )
        )

    print("\nCreated:")
    print(gfs_path)
    print(gefs_path)
    print(member_path)


if __name__ == "__main__":
    main()
