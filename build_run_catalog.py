from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a catalog from archived forecast-run manifests."
        )
    )

    parser.add_argument(
        "--archive-root",
        type=Path,
        default=Path("archive/runs"),
    )

    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path("archive/run_catalog"),
    )

    return parser.parse_args()


def rows_for(
    outputs: dict[str, dict[str, Any]],
    candidates: list[str],
) -> int:
    for candidate in candidates:
        metadata = outputs.get(candidate)

        if metadata is not None:
            return int(metadata.get("rows", 0) or 0)

    return 0


def read_consensus_metrics(
    run_directory: Path,
    run_id: str,
) -> dict[str, Any]:
    path = (
        run_directory
        / "output"
        / f"multimodel_consensus_{run_id}.csv"
    )

    if not path.exists():
        return {
            "equal_center_mean_c": None,
            "physics_consensus_mean_c": None,
            "aifs_minus_physics_c": None,
            "average_center_range_c": None,
            "average_structural_fraction": None,
            "greatest_disagreement_date": None,
            "greatest_disagreement_c": None,
        }

    frame = pd.read_csv(path)

    if frame.empty:
        return {
            "equal_center_mean_c": None,
            "physics_consensus_mean_c": None,
            "aifs_minus_physics_c": None,
            "average_center_range_c": None,
            "average_structural_fraction": None,
            "greatest_disagreement_date": None,
            "greatest_disagreement_c": None,
        }

    maximum_index = frame[
        "center_mean_range_c"
    ].idxmax()

    maximum_row = frame.loc[maximum_index]

    return {
        "equal_center_mean_c": float(
            frame["equal_center_mean_c"].mean()
        ),
        "physics_consensus_mean_c": float(
            frame["physics_consensus_mean_c"].mean()
        ),
        "aifs_minus_physics_c": float(
            frame[
                "aifs_minus_physics_consensus_c"
            ].mean()
        ),
        "average_center_range_c": float(
            frame["center_mean_range_c"].mean()
        ),
        "average_structural_fraction": float(
            frame[
                "structural_variance_fraction"
            ].mean()
        ),
        "greatest_disagreement_date": str(
            maximum_row["date"]
        ),
        "greatest_disagreement_c": float(
            maximum_row["center_mean_range_c"]
        ),
    }


def catalog_run(
    manifest_path: Path,
) -> dict[str, Any]:
    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )

    run_directory = manifest_path.parent
    run_id = str(manifest["run_id"])

    outputs = {
        str(record["path"]): record
        for record in manifest.get("outputs", [])
    }

    raw_directories = manifest.get(
        "raw_data_directories",
        [],
    )

    raw_file_count = sum(
        int(record.get("file_count", 0))
        for record in raw_directories
    )

    raw_total_bytes = sum(
        int(record.get("total_bytes", 0))
        for record in raw_directories
    )

    verification_rows = sum(
        int(record.get("rows", 0) or 0)
        for path, record in outputs.items()
        if path.startswith(
            "output/verification/"
        )
    )

    record: dict[str, Any] = {
        "run_id": run_id,
        "initialization_date":
            manifest.get("initialization_date"),
        "cycle_utc": manifest.get("cycle_utc"),
        "snapshot_created_utc":
            manifest.get("snapshot_created_utc"),
        "schema_version":
            manifest.get("schema_version"),
        "git_branch":
            manifest.get("git", {}).get("branch"),
        "git_commit":
            manifest.get("git", {}).get("commit"),
        "working_tree_clean":
            manifest.get("git", {}).get(
                "working_tree_clean"
            ),
        "output_files": len(
            manifest.get("outputs", [])
        ),
        "source_scripts": len(
            manifest.get("scripts", [])
        ),
        "raw_directories": len(raw_directories),
        "raw_files": raw_file_count,
        "raw_total_bytes": raw_total_bytes,
        "raw_total_gb": (
            raw_total_bytes / 1_000_000_000
        ),
        "gfs_days": rows_for(
            outputs,
            [
                (
                    f"output/gfs_{run_id}_"
                    "global_daily_complete.csv"
                ),
                "output/gfs_global_daily_complete.csv",
            ],
        ),
        "gefs_days": rows_for(
            outputs,
            [
                f"output/gefs_{run_id}_daily_summary.csv"
            ],
        ),
        "gdps_days": rows_for(
            outputs,
            [
                (
                    f"output/gdps_{run_id}_"
                    "global_daily_complete.csv"
                )
            ],
        ),
        "icon_days": rows_for(
            outputs,
            [
                (
                    f"output/icon_{run_id}_"
                    "global_daily_complete.csv"
                )
            ],
        ),
        "geps_days": rows_for(
            outputs,
            [
                f"output/geps_{run_id}_daily_summary.csv"
            ],
        ),
        "ifs_ens_days": rows_for(
            outputs,
            [
                (
                    f"output/ecmwf_ens_{run_id}_"
                    "daily_summary.csv"
                )
            ],
        ),
        "aifs_ens_days": rows_for(
            outputs,
            [
                (
                    f"output/aifs_ens_{run_id}_"
                    "daily_summary.csv"
                )
            ],
        ),
        "consensus_days": rows_for(
            outputs,
            [
                (
                    f"output/multimodel_consensus_"
                    f"{run_id}.csv"
                )
            ],
        ),
        "era5t_archive_days": rows_for(
            outputs,
            ["output/era5t_global_daily.csv"],
        ),
        "verification_rows": verification_rows,
    }

    record.update(
        read_consensus_metrics(
            run_directory,
            run_id,
        )
    )

    complete_models = [
        record["gfs_days"] > 0,
        record["gefs_days"] > 0,
        record["gdps_days"] > 0,
        record["geps_days"] > 0,
        record["ifs_ens_days"] > 0,
        record["aifs_ens_days"] > 0,
        record["consensus_days"] > 0,
    ]

    if all(complete_models):
        record["forecast_status"] = (
            "FORECAST_COMPLETE"
        )
    elif any(complete_models):
        record["forecast_status"] = "PARTIAL"
    else:
        record["forecast_status"] = "EMPTY"

    record["verification_status"] = (
        "VERIFIED"
        if verification_rows > 0
        else "WAITING_FOR_ERA5T"
    )

    return record


def main() -> None:
    args = parse_args()

    manifests = sorted(
        args.archive_root.glob(
            "*/manifest.json"
        )
    )

    if not manifests:
        raise SystemExit(
            "No archived run manifests found in "
            f"{args.archive_root}"
        )

    records = [
        catalog_run(path)
        for path in manifests
    ]

    frame = pd.DataFrame(records)

    frame = (
        frame
        .sort_values(
            [
                "initialization_date",
                "cycle_utc",
            ]
        )
        .reset_index(drop=True)
    )

    args.output_prefix.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    csv_path = args.output_prefix.with_suffix(
        ".csv"
    )

    json_path = args.output_prefix.with_suffix(
        ".json"
    )

    frame.to_csv(
        csv_path,
        index=False,
    )

    json_path.write_text(
        frame.to_json(
            orient="records",
            indent=2,
        ),
        encoding="utf-8",
    )

    columns = [
        "run_id",
        "forecast_status",
        "verification_status",
        "gfs_days",
        "gefs_days",
        "gdps_days",
        "icon_days",
        "geps_days",
        "ifs_ens_days",
        "aifs_ens_days",
        "consensus_days",
        "raw_files",
        "raw_total_gb",
        "equal_center_mean_c",
        "average_center_range_c",
        "average_structural_fraction",
    ]

    print("\nForecast-run catalog")
    print(
        frame[columns].to_string(
            index=False
        )
    )

    print("\nCreated:")
    print(csv_path)
    print(json_path)


if __name__ == "__main__":
    main()
