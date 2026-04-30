"""Form and password helpers built around pypdf."""

from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfWriter

from lembar.common import PdfToolError, reader, write_pdf


def list_fields(input_pdf: Path) -> dict[str, object]:
    """Return AcroForm fields keyed by field name."""
    fields = reader(input_pdf).get_fields()
    return fields or {}


def fill_form(input_pdf: Path, output: Path, data_file: Path, flatten: bool = False) -> None:
    """Fill AcroForm fields from a JSON object and optionally flatten annotations."""
    data = json.loads(data_file.read_text(encoding="utf-8"))
    source = reader(input_pdf)
    writer = PdfWriter()
    writer.clone_document_from_reader(source)
    for page in writer.pages:
        writer.update_page_form_field_values(page, data)
    if flatten:
        for page in writer.pages:
            if "/Annots" in page:
                del page["/Annots"]
    write_pdf(writer, output)


def flatten_form(input_pdf: Path, output: Path) -> None:
    """Remove form annotations after cloning the document."""
    source = reader(input_pdf)
    writer = PdfWriter()
    writer.clone_document_from_reader(source)
    for page in writer.pages:
        if "/Annots" in page:
            del page["/Annots"]
    write_pdf(writer, output)


def encrypt_pdf(input_pdf: Path, output: Path, password: str) -> None:
    """Encrypt a PDF with a user password."""
    source = reader(input_pdf)
    writer = PdfWriter()
    writer.clone_document_from_reader(source)
    writer.encrypt(password)
    write_pdf(writer, output)


def decrypt_pdf(input_pdf: Path, output: Path, password: str) -> None:
    """Decrypt a PDF with a user password and write an unencrypted copy."""
    source = reader(input_pdf)
    if source.is_encrypted and source.decrypt(password) == 0:
        raise PdfToolError("invalid password")
    writer = PdfWriter()
    writer.clone_document_from_reader(source)
    write_pdf(writer, output)
