"""Page-level PDF transformations built on pypdf."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter

from lembar.common import PdfToolError, all_except, clone_metadata, copy_pages, reader, selected_indices, write_pdf
from lembar.signatures import PdfSignatureError, list_signatures


def merge_pdfs(inputs: list[Path], output: Path, preserve_as_attachments: bool = False) -> list[Path]:
    """Merge PDFs and optionally attach original signed PDFs.

    Merging rewrites PDF structure, so original cryptographic signatures do not
    remain valid for the merged pages. Returning the signed inputs lets callers
    warn users, and attaching originals preserves the signed files byte-for-byte
    as evidence inside the merged output.
    """
    signed_inputs = _signed_inputs(inputs)
    writer = _merged_writer(inputs)
    if preserve_as_attachments:
        for signed_input in signed_inputs:
            writer.add_attachment(signed_input.name, signed_input.read_bytes())
    write_pdf(writer, output)
    return signed_inputs


def _merged_writer(inputs: list[Path]) -> PdfWriter:
    """Create a writer containing every page from the input PDFs."""
    writer = PdfWriter()
    for pdf in inputs:
        source = reader(pdf)
        if source.is_encrypted:
            raise PdfToolError(f"encrypted PDF cannot be merged without decrypting: {pdf}")
        for page in source.pages:
            writer.add_page(page)
    return writer


def _signed_inputs(inputs: list[Path]) -> list[Path]:
    """Return input PDFs that contain at least one digital signature."""
    signed: list[Path] = []
    for pdf in inputs:
        try:
            if list_signatures(pdf):
                signed.append(pdf)
        except PdfSignatureError:
            continue
    return signed


def extract_pages(input_pdf: Path, pages: str, output: Path) -> None:
    """Write selected pages to a new PDF."""
    source = reader(input_pdf)
    indices = selected_indices(pages, len(source.pages))
    writer = copy_pages(source, indices)
    clone_metadata(source, writer)
    write_pdf(writer, output)


def delete_pages(input_pdf: Path, pages: str, output: Path) -> None:
    """Write a new PDF with selected pages removed."""
    source = reader(input_pdf)
    indices = all_except(selected_indices(pages, len(source.pages)), len(source.pages))
    writer = copy_pages(source, indices)
    clone_metadata(source, writer)
    write_pdf(writer, output)


def reorder_pages(input_pdf: Path, pages: str, output: Path) -> None:
    """Write pages in exactly the order described by the page range string."""
    source = reader(input_pdf)
    writer = copy_pages(source, selected_indices(pages, len(source.pages)))
    clone_metadata(source, writer)
    write_pdf(writer, output)


def rotate_pages(input_pdf: Path, pages: str, degrees: int, output: Path) -> None:
    """Rotate selected pages clockwise by a multiple of 90 degrees."""
    if degrees % 90 != 0:
        raise PdfToolError("rotation degrees must be a multiple of 90")
    source = reader(input_pdf)
    selected = set(selected_indices(pages, len(source.pages)))
    writer = PdfWriter()
    for index, page in enumerate(source.pages):
        if index in selected:
            page = page.rotate(degrees)
        writer.add_page(page)
    clone_metadata(source, writer)
    write_pdf(writer, output)


def split_pdf(input_pdf: Path, output_dir: Path, prefix: str = "page") -> list[Path]:
    """Split a PDF into one output file per page."""
    source = reader(input_pdf)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, page in enumerate(source.pages, start=1):
        writer = PdfWriter()
        writer.add_page(page)
        output = output_dir / f"{prefix}-{index}.pdf"
        write_pdf(writer, output)
        paths.append(output)
    return paths


def crop_pages(input_pdf: Path, pages: str, box: tuple[float, float, float, float], output: Path) -> None:
    """Set the crop box of selected pages.

    Coordinates use PDF points in the page coordinate system:
    `(left, bottom, right, top)`.
    """
    source = reader(input_pdf)
    selected = set(selected_indices(pages, len(source.pages)))
    writer = PdfWriter()
    for index, page in enumerate(source.pages):
        if index in selected:
            page.cropbox.lower_left = (box[0], box[1])
            page.cropbox.upper_right = (box[2], box[3])
        writer.add_page(page)
    clone_metadata(source, writer)
    write_pdf(writer, output)


def resize_pages(input_pdf: Path, pages: str, width: float, height: float, output: Path) -> None:
    """Scale selected page content to fit within a new media/crop box."""
    source = reader(input_pdf)
    selected = set(selected_indices(pages, len(source.pages)))
    writer = PdfWriter()
    for index, page in enumerate(source.pages):
        if index in selected:
            old_width = float(page.mediabox.width)
            old_height = float(page.mediabox.height)
            scale = min(width / old_width, height / old_height)
            page.scale_by(scale)
            page.mediabox.upper_right = (width, height)
            page.cropbox.upper_right = (width, height)
        writer.add_page(page)
    clone_metadata(source, writer)
    write_pdf(writer, output)


def compress_pdf(input_pdf: Path, output: Path) -> None:
    """Compress page content streams without changing page order or geometry."""
    source = reader(input_pdf)
    writer = PdfWriter()
    for page in source.pages:
        page.compress_content_streams()
        writer.add_page(page)
    clone_metadata(source, writer)
    write_pdf(writer, output)
