from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


RAW_MODELS = [
    "gfs",
    "gefs",
    "gdps",
    "geps",
    "icon",
    "ecmwf_ens",
    "aifs_ens",
]

SCRIPT_REQUIREMENTS = {
    "download_gfs.py": [
        "--date",
        "--cycle",
        "--max-hour",
    ],
    "calculate_gfs_global.py": [
        "--date",
        "--cycle",
    ],
    "download_gefs.py": [
        "--date",
        "--cycle",
        "--max-hour",
    ],
    "calculate_gefs_global.py": [
        "--date",
        "--cycle",
    ],
    "download_gdps.py": [
        "--date",
        "--cycle",
        "--max-hour",
    ],
    "calculate_gdps_global.py": [
        "--date",
        "--cycle",
    ],
    "download_geps.py": [
        "--date",
        "--cycle",
        "--max-hour",
    ],
    "calculate_geps_global.py": [
        "--date",
        "--cycle",
    ],
    "download_ecmwf_ens.py": [
        "--date",
        "--cycle",
        "--max-hour",
    ],
    "calculate_ecmwf_ens_global.py": [
        "--date",
        "--cycle",
    ],
    "download_aifs_ens.py": [
        "--date",
        "--cycle",
        "--max-hour",
    ],
    "calculate_aifs_ens_global.py": [
        "--date",
        "--cycle",
    ],
    "build_multimodel_consensus.py": [
        "--date",
        "--cycle",
    ],
}

DATE_LITERAL = re.compile(
    r"\b20\d{6}\b"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--run-id",
        default="20260728_00z",
    )

    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
    )

    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path(
            "archive/multicycle_readiness"
        ),
    )

    return parser.parse_args()


def add_finding(
    findings: list[dict[str, Any]],
    *,
    severity: str,
    category: str,
    item: str,
    finding: str,
    recommendation: str,
) -> None:
    findings.append(
        {
            "severity": severity,
            "category": category,
            "item": item,
            "finding": finding,
            "recommendation": recommendation,
        }
    )


def git_status() -> list[str] | None:
    try:
        result = subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        return result.stdout.splitlines()

    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return None


def main() -> None:
    args = parse_args()

    manifest_path = args.manifest

    if manifest_path is None:
        manifest_path = (
            Path("archive/runs")
            / args.run_id
            / "manifest.json"
        )

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Missing manifest: {manifest_path}"
        )

    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8"
        )
    )

    run_id = str(manifest["run_id"])

    findings: list[dict[str, Any]] = []

    raw_paths = {
        str(record["path"])
        for record in manifest.get(
            "raw_data_directories",
            [],
        )
    }

    for model in RAW_MODELS:
        expected = f"data/{model}/{run_id}"

        if Path(expected).is_dir():
            add_finding(
                findings,
                severity="PASS",
                category="raw_data",
                item=model,
                finding=(
                    f"Run-scoped raw directory exists: "
                    f"{expected}"
                ),
                recommendation="None.",
            )
        else:
            add_finding(
                findings,
                severity="ERROR",
                category="raw_data",
                item=model,
                finding=(
                    "No run-scoped raw directory exists for "
                    f"{model}: {expected}"
                ),
                recommendation=(
                    "Move or copy this model's raw files "
                    "into a run-specific directory before "
                    "executing another cycle."
                ),
            )

    output_paths = [
        str(path)
        for path in Path("output").glob("gfs_*")
        if path.is_file()
        and not path.is_symlink()
    ]

    generic_forecast_outputs = [
        path
        for path in output_paths
        if path.startswith("output/gfs_")
        and run_id not in path
    ]

    for path in generic_forecast_outputs:
        add_finding(
            findings,
            severity="ERROR",
            category="output_scoping",
            item=path,
            finding=(
                "Forecast output is not run-scoped and "
                "can be overwritten by the next cycle."
            ),
            recommendation=(
                f"Rename or copy it so the filename "
                f"contains {run_id}."
            ),
        )

    if not generic_forecast_outputs:
        add_finding(
            findings,
            severity="PASS",
            category="output_scoping",
            item="forecast_outputs",
            finding=(
                "No generic GFS forecast outputs detected."
            ),
            recommendation="None.",
        )

    for script_name, required_tokens in (
        SCRIPT_REQUIREMENTS.items()
    ):
        path = Path(script_name)

        if not path.exists():
            add_finding(
                findings,
                severity="ERROR",
                category="script_interface",
                item=script_name,
                finding="Script is missing.",
                recommendation=(
                    "Restore or create the required script."
                ),
            )
            continue

        text = path.read_text(
            encoding="utf-8"
        )

        missing_tokens = [
            token
            for token in required_tokens
            if token not in text
        ]

        if missing_tokens:
            add_finding(
                findings,
                severity="ERROR",
                category="script_interface",
                item=script_name,
                finding=(
                    "Missing run parameters: "
                    f"{', '.join(missing_tokens)}"
                ),
                recommendation=(
                    "Parameterize the script before adding "
                    "it to the automated orchestrator."
                ),
            )
        else:
            add_finding(
                findings,
                severity="PASS",
                category="script_interface",
                item=script_name,
                finding=(
                    "Required run parameters were found."
                ),
                recommendation="None.",
            )

        literals = sorted(
            set(
                DATE_LITERAL.findall(text)
            )
        )

        if literals:
            add_finding(
                findings,
                severity="WARN",
                category="hardcoded_date",
                item=script_name,
                finding=(
                    "Date literals found: "
                    f"{', '.join(literals)}"
                ),
                recommendation=(
                    "Confirm these are defaults or examples, "
                    "not active hardcoded run dates."
                ),
            )

    status = git_status()

    if status is None:
        add_finding(
            findings,
            severity="WARN",
            category="git",
            item="repository",
            finding="Git status could not be determined.",
            recommendation=(
                "Run git status manually."
            ),
        )
    elif status:
        add_finding(
            findings,
            severity="WARN",
            category="git",
            item="repository",
            finding=(
                f"Working tree contains "
                f"{len(status)} uncommitted entries."
            ),
            recommendation=(
                "Commit the pipeline and snapshot metadata "
                "before launching a new forecast cycle."
            ),
        )
    else:
        add_finding(
            findings,
            severity="PASS",
            category="git",
            item="repository",
            finding="Working tree is clean.",
            recommendation="None.",
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

    columns = [
        "severity",
        "category",
        "item",
        "finding",
        "recommendation",
    ]

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=columns,
        )

        writer.writeheader()
        writer.writerows(findings)

    json_path.write_text(
        json.dumps(
            findings,
            indent=2,
        ),
        encoding="utf-8",
    )

    ordering = {
        "ERROR": 0,
        "WARN": 1,
        "PASS": 2,
    }

    findings.sort(
        key=lambda record: (
            ordering[record["severity"]],
            record["category"],
            record["item"],
        )
    )

    print("\nMulti-cycle readiness audit\n")

    for record in findings:
        print(
            f"[{record['severity']:5s}] "
            f"{record['category']:18s} "
            f"{record['item']}"
        )

        print(
            f"        {record['finding']}"
        )

    errors = sum(
        record["severity"] == "ERROR"
        for record in findings
    )

    warnings = sum(
        record["severity"] == "WARN"
        for record in findings
    )

    passes = sum(
        record["severity"] == "PASS"
        for record in findings
    )

    print("\nAudit summary")
    print(f"Errors:   {errors}")
    print(f"Warnings: {warnings}")
    print(f"Passes:   {passes}")

    print("\nCreated:")
    print(csv_path)
    print(json_path)

    if errors:
        print(
            "\nAUTOMATION BLOCKED: resolve all "
            "ERROR findings before launching "
            "another forecast cycle."
        )

        raise SystemExit(2)

    print(
        "\nAUTOMATION READY: no blocking "
        "multi-cycle errors remain."
    )


if __name__ == "__main__":
    main()
