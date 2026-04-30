"""Read-only inspection commands for PDF metadata and page geometry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader


class PdfInspectionError(Exception):
    """Raised when a PDF cannot be inspected."""


@dataclass(frozen=True)
class PdfBox:
    left: float
    bottom: float
    right: float
    top: float
    width: float
    height: float

    def to_dict(self) -> dict[str, float]:
        return {
            "left": self.left,
            "bottom": self.bottom,
            "right": self.right,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class PdfPageInfo:
    page: int
    width: float
    height: float
    rotation: int
    media_box: PdfBox
    crop_box: PdfBox
    trim_box: PdfBox | None
    bleed_box: PdfBox | None
    art_box: PdfBox | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "width": self.width,
            "height": self.height,
            "rotation": self.rotation,
            "media_box": self.media_box.to_dict(),
            "crop_box": self.crop_box.to_dict(),
            "trim_box": self.trim_box.to_dict() if self.trim_box else None,
            "bleed_box": self.bleed_box.to_dict() if self.bleed_box else None,
            "art_box": self.art_box.to_dict() if self.art_box else None,
        }


@dataclass(frozen=True)
class PdfInfo:
    path: str
    file_size: int
    page_count: int
    encrypted: bool
    metadata: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "file_size": self.file_size,
            "page_count": self.page_count,
            "encrypted": self.encrypted,
            "metadata": self.metadata,
        }


def inspect_pdf(path: str | Path) -> PdfInfo:
    """Return high-level file, encryption, page count, and metadata details."""
    pdf_path = _validate_pdf_path(path)
    reader = _reader(pdf_path)
    return PdfInfo(
        path=str(pdf_path),
        file_size=pdf_path.stat().st_size,
        page_count=len(reader.pages) if not reader.is_encrypted else 0,
        encrypted=reader.is_encrypted,
        metadata=_metadata(reader),
    )


def inspect_pages(path: str | Path) -> list[PdfPageInfo]:
    """Return page dimensions, rotation, and page boxes for every page."""
    pdf_path = _validate_pdf_path(path)
    reader = _reader(pdf_path)
    if reader.is_encrypted:
        raise PdfInspectionError("encrypted PDFs cannot be inspected without a password")

    pages: list[PdfPageInfo] = []
    for index, page in enumerate(reader.pages, start=1):
        crop_box = _box(page.cropbox)
        pages.append(
            PdfPageInfo(
                page=index,
                width=crop_box.width,
                height=crop_box.height,
                rotation=int(page.rotation or 0),
                media_box=_box(page.mediabox),
                crop_box=crop_box,
                trim_box=_optional_box(getattr(page, "trimbox", None)),
                bleed_box=_optional_box(getattr(page, "bleedbox", None)),
                art_box=_optional_box(getattr(page, "artbox", None)),
            )
        )
    return pages


def _validate_pdf_path(path: str | Path) -> Path:
    pdf_path = Path(path).expanduser()
    if not pdf_path.exists():
        raise PdfInspectionError(f"file not found: {pdf_path}")
    if not pdf_path.is_file():
        raise PdfInspectionError(f"not a file: {pdf_path}")
    return pdf_path


def _reader(path: Path) -> PdfReader:
    try:
        return PdfReader(path)
    except Exception as exc:  # noqa: BLE001 - pypdf has several parse-specific exceptions.
        raise PdfInspectionError(f"could not read PDF: {exc}") from exc


def _metadata(reader: PdfReader) -> dict[str, str]:
    if reader.is_encrypted or reader.metadata is None:
        return {}
    return {
        str(key).lstrip("/"): str(value)
        for key, value in reader.metadata.items()
        if value is not None
    }


def _optional_box(value: Any) -> PdfBox | None:
    return _box(value) if value is not None else None


def _box(value: Any) -> PdfBox:
    left = float(value.left)
    bottom = float(value.bottom)
    right = float(value.right)
    top = float(value.top)
    return PdfBox(
        left=left,
        bottom=bottom,
        right=right,
        top=top,
        width=right - left,
        height=top - bottom,
    )
