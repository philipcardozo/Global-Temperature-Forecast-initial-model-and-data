from __future__ import annotations

from pathlib import Path

import pandas as pd


FILES = {
    "GFS": Path(
        "output/verification/"
        "gfs_20260728_00z_vs_era5t.csv"
    ),
    "GEFS": Path(
        "output/verification/"
        "gefs_20260728_00z_vs_era5t.csv"
    ),
    "GDPS": Path(
        "output/verification/"
        "gdps_20260728_00z_vs_era5t.csv"
    ),
    "ICON": Path(
        "output/verification/"
        "icon_20260728_00z_vs_era5t.csv"
    ),
    "GEPS": Path(
        "output/verification/"
        "geps_20260728_00z_vs_era5t.csv"
    ),
    "IFS ENS": Path(
        "output/verification/"
        "ecmwf_ens_20260728_00z_vs_era5t.csv"
    ),
    "AIFS ENS": Path(
        "output/verification/"
        "aifs_ens_20260728_00z_vs_era5t.csv"
    ),
    "Multimodel": Path(
        "output/verification/"
        "multimodel_consensus_"
        "20260728_00z_vs_era5t.csv"
    ),
}


def count_rows(path: Path) -> int | None:
    if not path.exists():
        return None

    try:
        return len(pd.read_csv(path))
    except pd.errors.EmptyDataError:
        return 0


def main() -> None:
    print("Verification status\n")

    for name, path in FILES.items():
        rows = count_rows(path)

        if rows is None:
            status = "FILE MISSING"
        elif rows == 0:
            status = "WAITING FOR ERA5T"
        else:
            status = f"{rows} VERIFIED DAYS"

        print(f"{name:14s}: {status}")

    era5t_path = Path(
        "output/era5t_global_daily.csv"
    )

    print("\nERA5T")

    if not era5t_path.exists():
        print("Archive missing")
        return

    era5t = pd.read_csv(era5t_path)

    complete = (
        era5t["complete_matched_6h_day"]
        .astype(str)
        .str.strip()
        .str.lower()
        .eq("true")
    )

    print(
        "Complete matched-6h days:",
        int(complete.sum()),
    )

    if complete.any():
        dates = pd.to_datetime(
            era5t.loc[
                complete,
                "date_utc",
            ],
            utc=True,
        )

        print(
            "First complete date:",
            dates.min().strftime("%Y-%m-%d"),
        )

        print(
            "Latest complete date:",
            dates.max().strftime("%Y-%m-%d"),
        )

        forecast_start = pd.Timestamp(
            "2026-07-28",
            tz="UTC",
        )

        days_until_overlap = (
            forecast_start.normalize()
            - dates.max().normalize()
        ).days

        if days_until_overlap > 0:
            print(
                "Days remaining before "
                "forecast verification can begin:",
                days_until_overlap,
            )
        else:
            print(
                "ERA5T has reached the "
                "forecast verification period."
            )


if __name__ == "__main__":
    main()
