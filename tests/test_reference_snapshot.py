"""Regression tests for the immutable 20260728_00z reference snapshot."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "20260728_00z"
RUN_DIRECTORY = ROOT / "archive" / "runs" / RUN_ID
MANIFEST_PATH = RUN_DIRECTORY / "manifest.json"
OUTPUT_INDEX_PATH = RUN_DIRECTORY / "output_index.csv"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def load_manifest() -> dict[str, Any]:
    """Load the immutable reference-run manifest."""

    value = json.loads(
        MANIFEST_PATH.read_text(
            encoding="utf-8",
        )
    )

    if not isinstance(value, dict):
        raise TypeError("Reference manifest must contain a JSON object.")

    return value


def load_output_index() -> list[dict[str, str]]:
    """Load the reference output index."""

    with OUTPUT_INDEX_PATH.open(
        encoding="utf-8",
        newline="",
    ) as stream:
        return list(csv.DictReader(stream))


def test_reference_snapshot_identity() -> None:
    """The immutable snapshot must retain its initialization identity."""

    manifest = load_manifest()

    assert manifest["initialization_date"] == "20260728"
    assert manifest["cycle_utc"] == "00"


def test_reference_manifest_output_contract() -> None:
    """Every indexed output must contain core integrity metadata."""

    manifest = load_manifest()
    outputs = manifest["outputs"]

    assert isinstance(outputs, list)
    assert len(outputs) == 49

    for output in outputs:
        assert isinstance(output, dict)

        path = output["path"]
        suffix = output["suffix"]
        size_bytes = output["size_bytes"]
        sha256 = output["sha256"]

        assert isinstance(path, str)
        assert isinstance(suffix, str)
        assert isinstance(size_bytes, int)
        assert isinstance(sha256, str)

        assert path.startswith("output/")
        assert Path(path).suffix == suffix
        assert size_bytes > 0
        assert SHA256_PATTERN.fullmatch(sha256)


def test_output_index_matches_manifest() -> None:
    """The CSV index and JSON manifest must describe the same outputs."""

    manifest = load_manifest()
    index_rows = load_output_index()

    manifest_outputs = manifest["outputs"]

    manifest_paths = {output["path"] for output in manifest_outputs}

    indexed_paths = {row["path"] for row in index_rows}

    manifest_hashes = {output["sha256"] for output in manifest_outputs}

    indexed_hashes = {row["sha256"] for row in index_rows}

    assert len(index_rows) == 49
    assert indexed_paths == manifest_paths
    assert indexed_hashes == manifest_hashes
