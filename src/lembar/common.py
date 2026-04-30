"""Shared helpers for CLI commands that read, select, and write PDF pages."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

from pypdf import PdfReader, PdfWriter


class PdfToolError(Exception):
    """Raised when a PDF tool cannot complete its work."""


def reader(path: str | Path) -> PdfReader:
    """Open a PDF path and convert parser failures into user-facing errors."""
    pdf_path = Path(path).expanduser()
    if not pdf_path.exists():
        raise PdfToolError(f"file not found: {pdf_path}")
    if not pdf_path.is_file():
        raise PdfToolError(f"not a file: {pdf_path}")
    try:
        return PdfReader(pdf_path)
    except Exception as exc:  # noqa: BLE001
        raise PdfToolError(f"could not read PDF: {exc}") from exc


def write_pdf(writer: PdfWriter, output: str | Path) -> None:
    """Write a PdfWriter to disk, creating the parent directory if needed."""
    output_path = Path(output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)


def selected_indices(spec: str, page_count: int) -> list[int]:
    """Convert a 1-based page range string into 0-based page indices.

    Supported forms include `all`, `*`, `1`, `1-3`, and `1,3,5-7`.
    Duplicate pages are preserved intentionally so reorder/extract commands can
    repeat pages when requested.
    """
    if spec.lower() in {"all", "*"}:
        return list(range(page_count))

    indices: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        match = re.fullmatch(r"(\d+)(?:-(\d+)?)?", part)
        if not match:
            raise PdfToolError(f"invalid page range: {part}")
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start < 1 or end < start or end > page_count:
            raise PdfToolError(f"page range out of bounds: {part}")
        indices.extend(range(start - 1, end))

    return indices


def all_except(indices: Iterable[int], page_count: int) -> list[int]:
    """Return every page index except those supplied."""
    excluded = set(indices)
    return [index for index in range(page_count) if index not in excluded]


def copy_pages(source: PdfReader, indices: Iterable[int]) -> PdfWriter:
    """Create a new writer containing selected pages from an existing reader."""
    writer = PdfWriter()
    for index in indices:
        writer.add_page(source.pages[index])
    return writer


def clone_metadata(source: PdfReader, writer: PdfWriter) -> None:
    """Copy simple document metadata into a new writer when available."""
    if source.metadata:
        writer.add_metadata({str(key): str(value) for key, value in source.metadata.items() if value is not None})
