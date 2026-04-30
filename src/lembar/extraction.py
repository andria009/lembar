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
            tables = _usable_tables(page.extract_tables())
            for table_index, table in enumerate(tables, start=1):
                output = output_dir / f"{prefix}-p{page_index + 1}-{table_index}.csv"
                with output.open("w", newline="", encoding="utf-8") as handle:
                    csv.writer(handle, quoting=csv.QUOTE_NONNUMERIC, lineterminator="\n").writerows(
                        _postprocess_table(_normalized_table(table))
                    )
                paths.append(output)
    return paths


def _usable_tables(tables: list[list[list[str | None]]]) -> list[list[list[str | None]]]:
    """Drop tiny fragment tables when a full table was detected on the page."""
    if not tables:
        return []
    largest_cell_count = max(_non_empty_cell_count(table) for table in tables)
    if largest_cell_count < 6:
        return tables
    return [
        table
        for table in tables
        if _non_empty_cell_count(table) >= max(6, largest_cell_count // 3) and _column_count(table) > 1
    ]


def _non_empty_cell_count(table: list[list[str | None]]) -> int:
    return sum(1 for row in table for cell in row if cell and cell.strip())


def _column_count(table: list[list[str | None]]) -> int:
    return max((len(row) for row in table), default=0)


def _normalized_table(table: list[list[str | None]]) -> list[list[str | int | float]]:
    """Normalize pdfplumber table cells before CSV serialization."""
    return [[_csv_value(_normalized_cell(cell)) for cell in row] for row in table]


def _postprocess_table(table: list[list[str | int | float]]) -> list[list[str | int | float]]:
    """Apply table-shape fixes after generic cell normalization."""
    if _looks_like_jenjang_table(table):
        return _compact_jenjang_table(table)
    return table


def _looks_like_jenjang_table(table: list[list[str | int | float]]) -> bool:
    text = " ".join(str(cell) for row in table[:4] for cell in row if cell != "")
    return "Jenjang Jabatan Sumber Daya Manusia" in text and "Ilmu Pengetahuan dan Teknologi" in text


def _compact_jenjang_table(table: list[list[str | int | float]]) -> list[list[str | int | float]]:
    """Compact BRIN-style merged-header tables into their logical columns.

    pdfplumber can split the grouped "Jenjang Jabatan ..." header into many
    physical columns. Data rows are then spread across empty spacer columns.
    This pass groups continuation rows under the preceding numbered row and
    maps the physical columns back to the visible logical table.
    """
    rows = [_pad_row(row, 19) for row in table]
    output: list[list[str | int | float]] = [
        [
            "No",
            "Kategori",
            "Hasil Kerja",
            "Indikator",
            "Target",
            "Satuan",
            "Penjelasan",
            "Bukti Kelengkapan",
            "Ahli Utama",
            "Ahli Madya",
            "Ahli Muda",
            "Ahli Pertama",
        ]
    ]

    index = 0
    while index < len(rows):
        row = rows[index]
        if not isinstance(row[0], int):
            index += 1
            continue

        block = [row]
        index += 1
        while index < len(rows) and not isinstance(rows[index][0], int):
            block.append(rows[index])
            index += 1

        output.append(
            [
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                _join_multiline_items(_collect_column_text(block, [7, 8])),
                _join_multiline_items(_collect_detail_text(block, [9, 10, 11])),
                _first_non_empty(block, [12, 13]),
                _first_non_empty(block, [14]),
                _first_non_empty(block, [15]),
                _first_non_empty(block, [16, 17]),
            ]
        )

    return output


def _pad_row(row: list[str | int | float], width: int) -> list[str | int | float]:
    return [*row, *([""] * max(0, width - len(row)))]


def _collect_column_text(rows: list[list[str | int | float]], columns: list[int]) -> list[str]:
    values: list[str] = []
    for row in rows:
        for column in columns:
            value = row[column]
            if isinstance(value, str) and value:
                values.append(value)
    return values


def _collect_detail_text(rows: list[list[str | int | float]], columns: list[int]) -> list[str]:
    for column in columns:
        value = rows[0][column]
        if isinstance(value, str) and "\n" in value:
            return [value]
    return _collect_column_text(rows, columns)


def _join_multiline_items(values: list[str]) -> str:
    text = " ".join(values)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\b(\d+)\.\s+", r"\n\1. ", text).strip()
    text = re.sub(r"(?<!\n)^(\d+)\. ", r"\1. ", text)
    return text


def _first_non_empty(rows: list[list[str | int | float]], columns: list[int]) -> str | int | float:
    for row in rows:
        for column in columns:
            if row[column] != "":
                return row[column]
    return ""


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
