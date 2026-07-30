from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


GENERIC_OUTPUTS = [
    Path("output/gfs_global_6hourly.csv"),
    Path("output/gfs_global_daily.csv"),
    Path("output/gfs_global_daily_complete.csv"),
    Path("output/era5t_global_hourly.csv"),
    Path("output/era5t_global_daily.csv"),
]

PACKAGE_NAMES = [
    "numpy",
    "pandas",
    "requests",
    "eccodes",
    "ecmwf-opendata",
    "cdsapi",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create an immutable snapshot and manifest "
            "for one forecast initialization."
        )
    )

    parser.add_argument(
        "--init-date",
        required=True,
        help="Initialization date in YYYYMMDD format.",
    )

    parser.add_argument(
        "--cycle",
        default="00",
        choices=("00", "06", "12", "18"),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing snapshot.",
    )

    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def run_command(
    command: list[str],
) -> str | None:
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )

        return result.stdout.strip()

    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return None


def package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}

    for package in PACKAGE_NAMES:
        try:
            versions[package] = (
                importlib.metadata.version(package)
            )
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None

    return versions


def file_metadata(
    path: Path,
    project_root: Path,
) -> dict[str, Any]:
    stat = path.stat()

    metadata: dict[str, Any] = {
        "path": str(
            path.relative_to(project_root)
        ),
        "size_bytes": stat.st_size,
        "modified_utc": datetime.fromtimestamp(
            stat.st_mtime,
            tz=timezone.utc,
        ).isoformat(),
        "sha256": sha256_file(path),
        "suffix": path.suffix.lower(),
    }

    if path.suffix.lower() == ".csv":
        try:
            frame = pd.read_csv(path)

            metadata["rows"] = len(frame)
            metadata["columns"] = frame.columns.tolist()

        except Exception as error:
            metadata["csv_read_error"] = (
                f"{type(error).__name__}: {error}"
            )

    elif path.suffix.lower() == ".json":
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8")
            )

            if isinstance(payload, list):
                metadata["json_records"] = len(payload)
            elif isinstance(payload, dict):
                metadata["json_keys"] = sorted(
                    payload.keys()
                )

        except Exception as error:
            metadata["json_read_error"] = (
                f"{type(error).__name__}: {error}"
            )

    return metadata


def discover_outputs(
    project_root: Path,
    run_id: str,
) -> list[Path]:
    output_root = project_root / "output"

    discovered: set[Path] = set()

    if output_root.exists():
        for path in output_root.rglob("*"):
            if (
                path.is_file()
                and run_id in path.name
            ):
                discovered.add(path)

    for relative_path in GENERIC_OUTPUTS:
        path = project_root / relative_path

        if path.exists() and path.is_file():
            discovered.add(path)

    return sorted(discovered)


def discover_scripts(
    project_root: Path,
) -> list[Path]:
    scripts: list[Path] = []

    for path in project_root.glob("*"):
        if (
            path.is_file()
            and path.suffix in {".py", ".sh"}
        ):
            scripts.append(path)

    return sorted(scripts)


def directory_inventory(
    directory: Path,
    project_root: Path,
) -> dict[str, Any]:
    files = [
        path
        for path in directory.rglob("*")
        if path.is_file()
    ]

    suffix_counts: dict[str, int] = {}

    for path in files:
        suffix = path.suffix.lower() or "<none>"

        suffix_counts[suffix] = (
            suffix_counts.get(suffix, 0) + 1
        )

    return {
        "path": str(
            directory.relative_to(project_root)
        ),
        "file_count": len(files),
        "total_bytes": sum(
            path.stat().st_size
            for path in files
        ),
        "suffix_counts": suffix_counts,
    }


def discover_raw_directories(
    project_root: Path,
    run_id: str,
) -> list[Path]:
    data_root = project_root / "data"

    if not data_root.exists():
        return []

    directories: set[Path] = set()

    for path in data_root.rglob("*"):
        if (
            path.is_dir()
            and path.name == run_id
        ):
            directories.add(path)

    return sorted(directories)


def copy_files(
    paths: list[Path],
    *,
    project_root: Path,
    archive_root: Path,
) -> None:
    for source in paths:
        relative_path = source.relative_to(
            project_root
        )

        destination = (
            archive_root / relative_path
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        shutil.copy2(
            source,
            destination,
        )


def git_information(
    project_root: Path,
) -> dict[str, Any]:
    branch = run_command(
        [
            "git",
            "-C",
            str(project_root),
            "branch",
            "--show-current",
        ]
    )

    commit = run_command(
        [
            "git",
            "-C",
            str(project_root),
            "rev-parse",
            "HEAD",
        ]
    )

    status = run_command(
        [
            "git",
            "-C",
            str(project_root),
            "status",
            "--porcelain",
        ]
    )

    return {
        "branch": branch,
        "commit": commit,
        "working_tree_clean": (
            status == ""
            if status is not None
            else None
        ),
        "status_porcelain": (
            status.splitlines()
            if status
            else []
        ),
    }


def write_file_index(
    path: Path,
    records: list[dict[str, Any]],
) -> None:
    columns = [
        "path",
        "size_bytes",
        "modified_utc",
        "sha256",
        "suffix",
        "rows",
        "json_records",
    ]

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=columns,
            extrasaction="ignore",
        )

        writer.writeheader()

        for record in records:
            writer.writerow(record)


def main() -> None:
    args = parse_args()

    try:
        datetime.strptime(
            args.init_date,
            "%Y%m%d",
        )
    except ValueError as error:
        raise SystemExit(
            "--init-date must use YYYYMMDD."
        ) from error

    project_root = Path.cwd().resolve()

    run_id = (
        f"{args.init_date}_{args.cycle}z"
    )

    archive_root = (
        project_root
        / "archive"
        / "runs"
        / run_id
    )

    if archive_root.exists():
        if not args.force:
            raise SystemExit(
                f"Snapshot already exists: "
                f"{archive_root}\n"
                "Use --force only when intentionally "
                "replacing it."
            )

        shutil.rmtree(archive_root)

    archive_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    outputs = discover_outputs(
        project_root,
        run_id,
    )

    if not outputs:
        raise SystemExit(
            f"No outputs found for {run_id}."
        )

    scripts = discover_scripts(
        project_root
    )

    raw_directories = (
        discover_raw_directories(
            project_root,
            run_id,
        )
    )

    print(f"Creating snapshot: {run_id}")
    print(f"Output files found: {len(outputs)}")
    print(f"Scripts found:      {len(scripts)}")
    print(
        "Raw run directories:",
        len(raw_directories),
    )

    copy_files(
        outputs,
        project_root=project_root,
        archive_root=archive_root,
    )

    copy_files(
        scripts,
        project_root=project_root,
        archive_root=(
            archive_root / "code_snapshot"
        ),
    )

    output_records = [
        file_metadata(
            path,
            project_root,
        )
        for path in outputs
    ]

    script_records = [
        file_metadata(
            path,
            project_root,
        )
        for path in scripts
    ]

    raw_inventory = [
        directory_inventory(
            directory,
            project_root,
        )
        for directory in raw_directories
    ]

    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "initialization_date": args.init_date,
        "cycle_utc": args.cycle,
        "snapshot_created_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "project_root_at_creation": str(
            project_root
        ),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "packages": package_versions(),
        },
        "git": git_information(
            project_root
        ),
        "outputs": output_records,
        "scripts": script_records,
        "raw_data_directories": raw_inventory,
    }

    manifest_path = (
        archive_root / "manifest.json"
    )

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    index_path = (
        archive_root / "output_index.csv"
    )

    write_file_index(
        index_path,
        output_records,
    )

    total_output_bytes = sum(
        record["size_bytes"]
        for record in output_records
    )

    print("\nSnapshot completed")
    print(f"Run ID:             {run_id}")
    print(f"Archived outputs:   {len(outputs)}")
    print(
        "Archived output MB:",
        f"{total_output_bytes / 1_000_000:.2f}",
    )
    print(f"Manifest:           {manifest_path}")
    print(f"Output index:       {index_path}")
    print(
        "Git commit:         ",
        manifest["git"]["commit"],
    )
    print(
        "Working tree clean: ",
        manifest["git"][
            "working_tree_clean"
        ],
    )


if __name__ == "__main__":
    main()
