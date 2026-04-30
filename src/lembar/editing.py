"""Overlay-style PDF editing commands.

These commands add new drawing instructions on top of existing pages. They do
not rewrite existing PDF content streams, so `redact_region` is a visual cover
and should be upgraded before it is used for sensitive redaction workflows.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.lib.colors import black
from reportlab.pdfgen import canvas

from pypdf import PdfReader, PdfWriter

from lembar.common import PdfToolError, clone_metadata, reader, selected_indices, write_pdf


def add_text(input_pdf: Path, output: Path, pages: str, text: str, x: float, y: float, size: float = 12, font: str = "Helvetica") -> None:
    """Overlay centered text at `(x, y)` on selected pages."""
    source = reader(input_pdf)
    selected = set(selected_indices(pages, len(source.pages)))
    writer = PdfWriter()
    for index, page in enumerate(source.pages):
        if index in selected:
            page.merge_page(_text_overlay(float(page.mediabox.width), float(page.mediabox.height), text, x, y, size, font))
        writer.add_page(page)
    clone_metadata(source, writer)
    write_pdf(writer, output)


def add_image(input_pdf: Path, output: Path, pages: str, image: Path, x: float, y: float, width: float, height: float) -> None:
    """Overlay an image rectangle on selected pages."""
    source = reader(input_pdf)
    selected = set(selected_indices(pages, len(source.pages)))
    writer = PdfWriter()
    for index, page in enumerate(source.pages):
        if index in selected:
            page.merge_page(_image_overlay(float(page.mediabox.width), float(page.mediabox.height), image, x, y, width, height))
        writer.add_page(page)
    clone_metadata(source, writer)
    write_pdf(writer, output)


def add_watermark(input_pdf: Path, output: Path, text: str, size: float = 48) -> None:
    """Add a translucent diagonal text watermark to every page."""
    source = reader(input_pdf)
    writer = PdfWriter()
    for page in source.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        page.merge_page(_watermark_overlay(width, height, text, size))
        writer.add_page(page)
    clone_metadata(source, writer)
    write_pdf(writer, output)


def add_page_numbers(input_pdf: Path, output: Path, start: int = 1, size: float = 10) -> None:
    """Add centered page numbers near the bottom of each page."""
    source = reader(input_pdf)
    writer = PdfWriter()
    for offset, page in enumerate(source.pages):
        width = float(page.mediabox.width)
        page.merge_page(_text_overlay(width, float(page.mediabox.height), str(start + offset), width / 2, 24, size, "Helvetica"))
        writer.add_page(page)
    clone_metadata(source, writer)
    write_pdf(writer, output)


def redact_region(input_pdf: Path, output: Path, pages: str, x: float, y: float, width: float, height: float) -> None:
    """Visually cover a rectangular region with black fill on selected pages."""
    source = reader(input_pdf)
    selected = set(selected_indices(pages, len(source.pages)))
    writer = PdfWriter()
    for index, page in enumerate(source.pages):
        if index in selected:
            page.merge_page(_rect_overlay(float(page.mediabox.width), float(page.mediabox.height), x, y, width, height))
        writer.add_page(page)
    clone_metadata(source, writer)
    write_pdf(writer, output)


def _text_overlay(page_width: float, page_height: float, text: str, x: float, y: float, size: float, font: str) -> PdfReader:
    """Create a one-page PDF overlay containing text."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    pdf.setFont(font, size)
    pdf.drawCentredString(x, y, text)
    pdf.save()
    buffer.seek(0)
    return PdfReader(buffer).pages[0]


def _image_overlay(page_width: float, page_height: float, image: Path, x: float, y: float, width: float, height: float) -> PdfReader:
    """Create a one-page PDF overlay containing an image."""
    if not image.exists():
        raise PdfToolError(f"image not found: {image}")
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    pdf.drawImage(str(image), x, y, width=width, height=height, mask="auto")
    pdf.save()
    buffer.seek(0)
    return PdfReader(buffer).pages[0]


def _watermark_overlay(page_width: float, page_height: float, text: str, size: float) -> PdfReader:
    """Create a one-page PDF overlay containing a diagonal watermark."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    pdf.saveState()
    pdf.translate(page_width / 2, page_height / 2)
    pdf.rotate(45)
    pdf.setFillColorRGB(0.7, 0.7, 0.7, alpha=0.35)
    pdf.setFont("Helvetica-Bold", size)
    pdf.drawCentredString(0, 0, text)
    pdf.restoreState()
    pdf.save()
    buffer.seek(0)
    return PdfReader(buffer).pages[0]


def _rect_overlay(page_width: float, page_height: float, x: float, y: float, width: float, height: float) -> PdfReader:
    """Create a one-page PDF overlay containing a filled rectangle."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    pdf.setFillColor(black)
    pdf.rect(x, y, width, height, stroke=0, fill=1)
    pdf.save()
    buffer.seek(0)
    return PdfReader(buffer).pages[0]
