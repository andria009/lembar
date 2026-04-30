"""Content extraction helpers for text, images, tables, and OCR."""

from __future__ import annotations

import csv
from pathlib import Path
import re
import subprocess

import pdfplumber
from pypdf import PdfReader

from lembar.common import PdfToolError, reader, selected_indices


def extract_text(input_pdf: Path, pages: str) -> str:
    """Extract text from selected pages using pypdf's text extractor."""
    source = reader(input_pdf)
    lines: list[str] = []
    for index in selected_indices(pages, len(source.pages)):
        text = source.pages[index].extract_text() or ""
        lines.append(text)
    return "\n\n".join(lines)


def extract_images(input_pdf: Path, pages: str, output_dir: Path, prefix: str = "image") -> list[Path]:
    """Save embedded images from selected pages to an output directory."""
    source = reader(input_pdf)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for page_index in selected_indices(pages, len(source.pages)):
        for image_index, image in enumerate(source.pages[page_index].images, start=1):
            output = output_dir / f"{prefix}-p{page_index + 1}-{image_index}-{image.name}"
            output.write_bytes(image.data)
            paths.append(output)
    return paths


def extract_tables(input_pdf: Path, pages: str, output_dir: Path, prefix: str = "table") -> list[Path]:
    """Extract tables with pdfplumber and write one CSV per detected table."""
    source = PdfReader(input_pdf)
    indices = set(selected_indices(pages, len(source.pages)))
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    with pdfplumber.open(input_pdf) as pdf:
        for page_index, page in enumerate(pdf.pages):
            if page_index not in indices:
                continue
            for table_index, table in enumerate(page.extract_tables(), start=1):
                output = output_dir / f"{prefix}-p{page_index + 1}-{table_index}.csv"
                with output.open("w", newline="", encoding="utf-8") as handle:
                    csv.writer(handle, quoting=csv.QUOTE_NONNUMERIC, lineterminator="\n").writerows(
                        _normalized_table(table)
                    )
                paths.append(output)
    return paths


def _normalized_table(table: list[list[str | None]]) -> list[list[str | int | float]]:
    """Normalize pdfplumber table cells before CSV serialization."""
    return [[_csv_value(_normalized_cell(cell)) for cell in row] for row in table]


def _normalized_cell(cell: str | None) -> str:
    """Clean a table cell while preserving intended numbered-list line breaks.

    PDF table extraction often inserts newlines for visual wrapping. Those
    should become spaces. Numbered list items that start a new line, such as
    `2. ...`, are kept as embedded newlines because they carry structure.
    """
    if cell is None:
        return ""

    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in cell.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    value = lines[0]
    for line in lines[1:]:
        if re.fullmatch(r"\d+\..*", line):
            value = f"{value.rstrip()} \n{line}"
        else:
            value = f"{value.rstrip()} {line}"
    return value.strip()


def _csv_value(value: str) -> str | int | float:
    """Cast numeric-looking cells so csv.QUOTE_NONNUMERIC leaves them unquoted."""
    if re.fullmatch(r"[+-]?\d+", value):
        return int(value)
    if re.fullmatch(r"[+-]?(?:\d+\.\d+|\d*\.\d+)", value):
        return float(value)
    return value


def ocr_pdf(input_pdf: Path, output: Path, language: str = "eng") -> None:
    """Run OCRmyPDF to add a searchable text layer to a scanned PDF."""
    command = [
        "ocrmypdf",
        "--skip-text",
        "-l",
        language,
        str(input_pdf),
        str(output),
    ]
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as exc:
        raise PdfToolError("ocrmypdf is not installed; install it to use the ocr command") from exc
    except subprocess.CalledProcessError as exc:
        raise PdfToolError(f"OCR failed with exit code {exc.returncode}") from exc
