"""Convert LinkedIn XLS/XLSX exports into Streamlit-friendly static CSV files."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def export_workbook(source: Path, prefix: str, output_dir: Path, header_rows: dict[str, int]) -> None:
    workbook = pd.ExcelFile(source)
    for sheet_name in workbook.sheet_names:
        frame = pd.read_excel(source, sheet_name=sheet_name, header=header_rows.get(sheet_name, 0))
        frame = frame.dropna(how="all").dropna(axis=1, how="all")
        frame.to_csv(output_dir / f"{prefix}_{slug(sheet_name)}.csv", index=False, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--followers", type=Path, required=True)
    parser.add_argument("--content", type=Path, required=True)
    parser.add_argument("--visitors", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/linkedin"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    export_workbook(args.followers, "followers", args.output, {})
    export_workbook(args.content, "content", args.output, {"Metrics": 1, "All posts": 1})
    export_workbook(args.visitors, "visitors", args.output, {})


if __name__ == "__main__":
    main()
