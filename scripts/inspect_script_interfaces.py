"""Statically inventory command-line interfaces in root-level Python scripts."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

OUTPUT_DIRECTORY = ROOT / "archive" / "engineering"

JSON_PATH = OUTPUT_DIRECTORY / "phase2_script_interfaces.json"

TEXT_PATH = OUTPUT_DIRECTORY / "phase2_script_interfaces.txt"


def is_main_guard(node: ast.AST) -> bool:
    """Return whether an AST node is an if __name__ == '__main__' guard."""

    if not isinstance(node, ast.If):
        return False

    comparison = node.test

    if not isinstance(comparison, ast.Compare):
        return False

    if len(comparison.ops) != 1:
        return False

    if not isinstance(
        comparison.ops[0],
        ast.Eq,
    ):
        return False

    left = comparison.left

    if not (isinstance(left, ast.Name) and left.id == "__name__"):
        return False

    if len(comparison.comparators) != 1:
        return False

    right = comparison.comparators[0]

    return isinstance(right, ast.Constant) and right.value == "__main__"


def constant_value(
    node: ast.AST,
) -> Any:
    """Return a simple constant value when statically available."""

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(
        node,
        ast.UnaryOp,
    ) and isinstance(
        node.op,
        ast.USub,
    ):
        value = constant_value(node.operand)

        if isinstance(
            value,
            int | float,
        ):
            return -value

    if isinstance(
        node,
        ast.List | ast.Tuple | ast.Set,
    ):
        values = [constant_value(element) for element in node.elts]

        if all(value is not None for value in values):
            return values

    return None


def inspect_script(
    path: Path,
) -> dict[str, Any]:
    """Inspect one Python script without executing it."""

    source = path.read_text(encoding="utf-8")

    tree = ast.parse(
        source,
        filename=str(path),
    )

    options: list[dict[str, Any]] = []

    positional_arguments: list[dict[str, Any]] = []

    imports_argparse = False
    defines_main = False
    has_main_guard = False

    for node in ast.walk(tree):
        if isinstance(
            node,
            ast.Import,
        ):
            imports_argparse = imports_argparse or any(
                alias.name == "argparse" for alias in node.names
            )

        if isinstance(
            node,
            ast.ImportFrom,
        ):
            imports_argparse = imports_argparse or node.module == "argparse"

        if isinstance(
            node,
            ast.FunctionDef | ast.AsyncFunctionDef,
        ):
            if node.name == "main":
                defines_main = True

        if is_main_guard(node):
            has_main_guard = True

        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        function = node.func

        if not (
            isinstance(
                function,
                ast.Attribute,
            )
            and function.attr == "add_argument"
        ):
            continue

        names = [
            argument.value
            for argument in node.args
            if (
                isinstance(
                    argument,
                    ast.Constant,
                )
                and isinstance(
                    argument.value,
                    str,
                )
            )
        ]

        keyword_values = {
            keyword.arg: constant_value(keyword.value)
            for keyword in node.keywords
            if keyword.arg is not None
        }

        record = {
            "names": names,
            "required": (keyword_values.get("required")),
            "default": (keyword_values.get("default")),
            "choices": (keyword_values.get("choices")),
            "action": (keyword_values.get("action")),
            "help": (keyword_values.get("help")),
            "line": getattr(
                node,
                "lineno",
                None,
            ),
        }

        if any(name.startswith("-") for name in names):
            options.append(record)
        else:
            positional_arguments.append(record)

    option_names = sorted(
        {
            name
            for option in options
            for name in option["names"]
            if name.startswith("--")
        }
    )

    return {
        "path": str(path.relative_to(ROOT)),
        "imports_argparse": (imports_argparse),
        "defines_main": defines_main,
        "has_main_guard": has_main_guard,
        "options": options,
        "option_names": option_names,
        "positional_arguments": (positional_arguments),
        "supports_date": ("--date" in option_names),
        "supports_cycle": ("--cycle" in option_names),
        "supports_run_id": ("--run-id" in option_names),
        "supports_max_hour": ("--max-hour" in option_names),
        "supports_overwrite": ("--overwrite" in option_names),
        "supports_dry_run": ("--dry-run" in option_names),
    }


def main() -> int:
    """Create JSON and text interface inventories."""

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    scripts = sorted(ROOT.glob("*.py"))

    records: list[dict[str, Any]] = []

    syntax_errors: list[dict[str, str]] = []

    for path in scripts:
        try:
            records.append(inspect_script(path))
        except SyntaxError as error:
            syntax_errors.append(
                {
                    "path": str(path.relative_to(ROOT)),
                    "error": str(error),
                }
            )

    inventory = {
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "script_count": len(scripts),
        "records": records,
        "syntax_errors": syntax_errors,
    }

    JSON_PATH.write_text(
        json.dumps(
            inventory,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        "PHASE 2 SCRIPT INTERFACE INVENTORY",
        "=" * 88,
        "",
        (f"Created UTC: {inventory['created_utc']}"),
        (f"Root-level Python scripts: {len(scripts)}"),
        "",
    ]

    for record in records:
        lines.extend(
            [
                record["path"],
                "-" * 88,
                (f"argparse: {record['imports_argparse']}"),
                (f"main function: {record['defines_main']}"),
                (f"main guard: {record['has_main_guard']}"),
                ("options: " + (", ".join(record["option_names"]) or "none detected")),
                (f"positional arguments: {len(record['positional_arguments'])}"),
                "",
            ]
        )

    missing_run_scope = [
        record["path"]
        for record in records
        if (
            record["imports_argparse"]
            and not (
                record["supports_run_id"]
                or (record["supports_date"] and record["supports_cycle"])
            )
        )
    ]

    no_argparse = [
        record["path"] for record in records if not record["imports_argparse"]
    ]

    lines.extend(
        [
            "SUMMARY",
            "=" * 88,
            "",
            ("Scripts with argparse but without --run-id or --date/--cycle:"),
        ]
    )

    if missing_run_scope:
        lines.extend(f"  {path}" for path in missing_run_scope)
    else:
        lines.append("  None")

    lines.extend(
        [
            "",
            "Scripts without argparse:",
        ]
    )

    if no_argparse:
        lines.extend(f"  {path}" for path in no_argparse)
    else:
        lines.append("  None")

    if syntax_errors:
        lines.extend(
            [
                "",
                "Syntax errors:",
            ]
        )

        for error in syntax_errors:
            lines.append(f"  {error['path']}: {error['error']}")

    TEXT_PATH.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print(TEXT_PATH.read_text(encoding="utf-8"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
