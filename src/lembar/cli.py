"""Argument parsing and command dispatch for the `lembar` CLI."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import sys
from pathlib import Path
from typing import Sequence

from lembar.common import PdfToolError
from lembar.editing import add_image, add_page_numbers, add_text, add_watermark, redact_region
from lembar.extraction import extract_images, extract_tables, extract_text, ocr_pdf
from lembar.forms import decrypt_pdf, encrypt_pdf, fill_form, flatten_form, list_fields
from lembar.inspection import PdfInspectionError, inspect_pages, inspect_pdf
from lembar.page_ops import (
    compress_pdf,
    crop_pages,
    delete_pages,
    extract_pages,
    merge_pdfs,
    reorder_pages,
    resize_pages,
    rotate_pages,
    split_pdf,
)
from lembar.signatures import PdfSignatureError, list_signatures


def main(argv: Sequence[str] | None = None) -> int:
    """Parse command-line arguments and dispatch to a subcommand handler."""
    parser = argparse.ArgumentParser(
        prog="lembar",
        description="Command-line tools for inspecting and working with PDF files.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    info = subcommands.add_parser(
        "info",
        help="Show high-level PDF information",
        description="Show high-level PDF information such as page count, encryption, and metadata.",
    )
    info.add_argument("pdf", type=Path, help="PDF file to inspect")
    info.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    info.set_defaults(handler=_info)

    pages_info = subcommands.add_parser(
        "pages-info",
        help="Show per-page dimensions and boxes",
        description="Show per-page dimensions, rotation, and page boxes.",
    )
    pages_info.add_argument("pdf", type=Path, help="PDF file to inspect")
    pages_info.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    pages_info.set_defaults(handler=_pages_info)

    _add_page_operation_commands(subcommands)
    _add_extraction_commands(subcommands)
    _add_editing_commands(subcommands)
    _add_security_form_commands(subcommands)

    signature_check = subcommands.add_parser(
        "signature-check",
        help="List digital signatures in a PDF",
        description="List digital signature fields and signature dictionaries in a PDF.",
    )
    signature_check.add_argument("pdf", type=Path, help="PDF file to inspect")
    signature_check.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output",
    )
    signature_check.add_argument(
        "--names-times",
        action="store_true",
        help="Print only signature order, signer name, and signing time",
    )
    signature_check.set_defaults(handler=_signature_check)

    args = parser.parse_args(argv)
    return args.handler(args)


def _add_page_operation_commands(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register commands that create new PDFs by changing page structure."""
    merge = subcommands.add_parser(
        "merge",
        help="Merge PDFs",
        description=(
            "Merge signed or unsigned PDFs. If signed inputs are detected, "
            "Lembar warns that original signatures will not validate on merged "
            "pages. Use --preserve-as-attachments to embed signed source PDFs "
            "unchanged as attachments."
        ),
    )
    merge.add_argument("output", type=Path)
    merge.add_argument("inputs", type=Path, nargs="+")
    merge.add_argument(
        "--preserve-as-attachments",
        action="store_true",
        help="Attach original signed input PDFs to preserve their signatures as original files",
    )
    merge.set_defaults(handler=_merge)

    split = subcommands.add_parser("split", help="Split PDF into one file per page")
    split.add_argument("pdf", type=Path)
    split.add_argument("output_dir", type=Path)
    split.add_argument("--prefix", default="page")
    split.set_defaults(handler=_split)

    extract = subcommands.add_parser("extract-pages", help="Extract selected pages")
    extract.add_argument("pdf", type=Path)
    extract.add_argument("output", type=Path)
    extract.add_argument("--pages", required=True)
    extract.set_defaults(handler=lambda args: _run_file_command(lambda: extract_pages(args.pdf, args.pages, args.output), args.output))

    delete = subcommands.add_parser("delete-pages", help="Delete selected pages")
    delete.add_argument("pdf", type=Path)
    delete.add_argument("output", type=Path)
    delete.add_argument("--pages", required=True)
    delete.set_defaults(handler=lambda args: _run_file_command(lambda: delete_pages(args.pdf, args.pages, args.output), args.output))

    reorder = subcommands.add_parser("reorder-pages", help="Write pages in a new order")
    reorder.add_argument("pdf", type=Path)
    reorder.add_argument("output", type=Path)
    reorder.add_argument("--pages", required=True)
    reorder.set_defaults(handler=lambda args: _run_file_command(lambda: reorder_pages(args.pdf, args.pages, args.output), args.output))

    rotate = subcommands.add_parser("rotate-pages", help="Rotate selected pages")
    rotate.add_argument("pdf", type=Path)
    rotate.add_argument("output", type=Path)
    rotate.add_argument("--pages", default="all")
    rotate.add_argument("--degrees", type=int, required=True)
    rotate.set_defaults(handler=lambda args: _run_file_command(lambda: rotate_pages(args.pdf, args.pages, args.degrees, args.output), args.output))

    crop = subcommands.add_parser("crop-pages", help="Crop selected pages to a PDF box")
    crop.add_argument("pdf", type=Path)
    crop.add_argument("output", type=Path)
    crop.add_argument("--pages", default="all")
    crop.add_argument("--box", nargs=4, type=float, metavar=("LEFT", "BOTTOM", "RIGHT", "TOP"), required=True)
    crop.set_defaults(handler=lambda args: _run_file_command(lambda: crop_pages(args.pdf, args.pages, tuple(args.box), args.output), args.output))

    resize = subcommands.add_parser("resize-pages", help="Resize selected pages")
    resize.add_argument("pdf", type=Path)
    resize.add_argument("output", type=Path)
    resize.add_argument("--pages", default="all")
    resize.add_argument("--width", type=float, required=True)
    resize.add_argument("--height", type=float, required=True)
    resize.set_defaults(handler=lambda args: _run_file_command(lambda: resize_pages(args.pdf, args.pages, args.width, args.height, args.output), args.output))

    compress = subcommands.add_parser("compress", help="Compress page content streams")
    compress.add_argument("pdf", type=Path)
    compress.add_argument("output", type=Path)
    compress.set_defaults(handler=lambda args: _run_file_command(lambda: compress_pdf(args.pdf, args.output), args.output))


def _add_extraction_commands(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register commands that extract content from PDFs."""
    text = subcommands.add_parser("extract-text", help="Extract text from pages")
    text.add_argument("pdf", type=Path)
    text.add_argument("--pages", default="all")
    text.add_argument("--output", type=Path)
    text.set_defaults(handler=_extract_text)

    images = subcommands.add_parser("extract-images", help="Extract embedded page images")
    images.add_argument("pdf", type=Path)
    images.add_argument("output_dir", type=Path)
    images.add_argument("--pages", default="all")
    images.add_argument("--prefix", default="image")
    images.set_defaults(handler=_extract_images)

    tables = subcommands.add_parser("extract-tables", help="Extract detected tables to CSV files")
    tables.add_argument("pdf", type=Path)
    tables.add_argument("output_dir", type=Path)
    tables.add_argument("--pages", default="all")
    tables.add_argument("--prefix", default="table")
    tables.set_defaults(handler=_extract_tables)

    ocr = subcommands.add_parser("ocr", help="OCR a scanned PDF using local ocrmypdf")
    ocr.add_argument("pdf", type=Path)
    ocr.add_argument("output", type=Path)
    ocr.add_argument("--language", default="eng")
    ocr.set_defaults(handler=lambda args: _run_file_command(lambda: ocr_pdf(args.pdf, args.output, args.language), args.output))


def _add_editing_commands(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register overlay-editing commands."""
    text = subcommands.add_parser("add-text", help="Overlay text on selected pages")
    text.add_argument("pdf", type=Path)
    text.add_argument("output", type=Path)
    text.add_argument("--pages", default="all")
    text.add_argument("--text", required=True)
    text.add_argument("--x", type=float, required=True)
    text.add_argument("--y", type=float, required=True)
    text.add_argument("--size", type=float, default=12)
    text.add_argument("--font", default="Helvetica")
    text.set_defaults(handler=lambda args: _run_file_command(lambda: add_text(args.pdf, args.output, args.pages, args.text, args.x, args.y, args.size, args.font), args.output))

    image = subcommands.add_parser("add-image", help="Overlay an image on selected pages")
    image.add_argument("pdf", type=Path)
    image.add_argument("output", type=Path)
    image.add_argument("--pages", default="all")
    image.add_argument("--image", type=Path, required=True)
    image.add_argument("--x", type=float, required=True)
    image.add_argument("--y", type=float, required=True)
    image.add_argument("--width", type=float, required=True)
    image.add_argument("--height", type=float, required=True)
    image.set_defaults(handler=lambda args: _run_file_command(lambda: add_image(args.pdf, args.output, args.pages, args.image, args.x, args.y, args.width, args.height), args.output))

    watermark = subcommands.add_parser("watermark", help="Add a text watermark")
    watermark.add_argument("pdf", type=Path)
    watermark.add_argument("output", type=Path)
    watermark.add_argument("--text", required=True)
    watermark.add_argument("--size", type=float, default=48)
    watermark.set_defaults(handler=lambda args: _run_file_command(lambda: add_watermark(args.pdf, args.output, args.text, args.size), args.output))

    numbers = subcommands.add_parser("page-numbers", help="Add page numbers")
    numbers.add_argument("pdf", type=Path)
    numbers.add_argument("output", type=Path)
    numbers.add_argument("--start", type=int, default=1)
    numbers.add_argument("--size", type=float, default=10)
    numbers.set_defaults(handler=lambda args: _run_file_command(lambda: add_page_numbers(args.pdf, args.output, args.start, args.size), args.output))

    redact = subcommands.add_parser("redact-region", help="Cover a rectangular region with a black box")
    redact.add_argument("pdf", type=Path)
    redact.add_argument("output", type=Path)
    redact.add_argument("--pages", default="all")
    redact.add_argument("--x", type=float, required=True)
    redact.add_argument("--y", type=float, required=True)
    redact.add_argument("--width", type=float, required=True)
    redact.add_argument("--height", type=float, required=True)
    redact.set_defaults(handler=lambda args: _run_file_command(lambda: redact_region(args.pdf, args.output, args.pages, args.x, args.y, args.width, args.height), args.output))


def _add_security_form_commands(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register form, encryption, and signature-validation commands."""
    fields = subcommands.add_parser("list-fields", help="List AcroForm fields")
    fields.add_argument("pdf", type=Path)
    fields.add_argument("--json", action="store_true")
    fields.set_defaults(handler=_list_fields)

    fill = subcommands.add_parser("fill-form", help="Fill AcroForm fields from a JSON file")
    fill.add_argument("pdf", type=Path)
    fill.add_argument("output", type=Path)
    fill.add_argument("--data", type=Path, required=True)
    fill.add_argument("--flatten", action="store_true")
    fill.set_defaults(handler=lambda args: _run_file_command(lambda: fill_form(args.pdf, args.output, args.data, args.flatten), args.output))

    flatten = subcommands.add_parser("flatten-form", help="Flatten form annotations")
    flatten.add_argument("pdf", type=Path)
    flatten.add_argument("output", type=Path)
    flatten.set_defaults(handler=lambda args: _run_file_command(lambda: flatten_form(args.pdf, args.output), args.output))

    encrypt = subcommands.add_parser("encrypt", help="Encrypt a PDF with a password")
    encrypt.add_argument("pdf", type=Path)
    encrypt.add_argument("output", type=Path)
    encrypt.add_argument("--password", required=True)
    encrypt.set_defaults(handler=lambda args: _run_file_command(lambda: encrypt_pdf(args.pdf, args.output, args.password), args.output))

    decrypt = subcommands.add_parser("decrypt", help="Decrypt a PDF with a password")
    decrypt.add_argument("pdf", type=Path)
    decrypt.add_argument("output", type=Path)
    decrypt.add_argument("--password", required=True)
    decrypt.set_defaults(handler=lambda args: _run_file_command(lambda: decrypt_pdf(args.pdf, args.output, args.password), args.output))

    validate = subcommands.add_parser("signature-validate", help="Best-effort signature validation summary")
    validate.add_argument("pdf", type=Path)
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(handler=_signature_validate)


def _info(args: argparse.Namespace) -> int:
    try:
        info = inspect_pdf(args.pdf)
    except PdfInspectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(info.to_dict(), indent=2))
        return 0

    print(f"File:      {info.path}")
    print(f"Size:      {info.file_size} bytes")
    print(f"Pages:     {info.page_count}")
    print(f"Encrypted: {_format_bool(info.encrypted)}")
    if info.metadata:
        print("Metadata:")
        for key, value in sorted(info.metadata.items()):
            print(f"  {key}: {value}")
    return 0


def _pages_info(args: argparse.Namespace) -> int:
    try:
        pages = inspect_pages(args.pdf)
    except PdfInspectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([page.to_dict() for page in pages], indent=2))
        return 0

    for page in pages:
        print(
            f"{page.page}\t"
            f"{_format_number(page.width)} x {_format_number(page.height)} pt\t"
            f"rotation {page.rotation}\t"
            f"crop {_format_box(page.crop_box)}"
        )
    return 0


def _split(args: argparse.Namespace) -> int:
    try:
        paths = split_pdf(args.pdf, args.output_dir, args.prefix)
    except PdfToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for path in paths:
        print(path)
    return 0


def _merge(args: argparse.Namespace) -> int:
    try:
        signed_inputs = merge_pdfs(args.inputs, args.output, args.preserve_as_attachments)
    except PdfToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if signed_inputs:
        print(
            "warning: merging digitally signed PDFs rewrites PDF bytes; original signatures "
            "will not validate on the merged pages.",
            file=sys.stderr,
        )
        if args.preserve_as_attachments:
            joined = ", ".join(str(path) for path in signed_inputs)
            print(f"warning: preserved signed originals as attachments: {joined}", file=sys.stderr)
        else:
            print(
                "warning: use --preserve-as-attachments to embed original signed PDFs unchanged.",
                file=sys.stderr,
            )
    print(args.output)
    return 0


def _extract_text(args: argparse.Namespace) -> int:
    try:
        text = extract_text(args.pdf, args.pages)
    except PdfToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(args.output)
    else:
        print(text)
    return 0


def _extract_images(args: argparse.Namespace) -> int:
    try:
        paths = extract_images(args.pdf, args.pages, args.output_dir, args.prefix)
    except PdfToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for path in paths:
        print(path)
    return 0


def _extract_tables(args: argparse.Namespace) -> int:
    try:
        paths = extract_tables(args.pdf, args.pages, args.output_dir, args.prefix)
    except PdfToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for path in paths:
        print(path)
    return 0


def _list_fields(args: argparse.Namespace) -> int:
    try:
        fields = list_fields(args.pdf)
    except PdfToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(fields, indent=2, default=str))
    else:
        for name, value in fields.items():
            print(f"{name}\t{value.get('/V', '') if isinstance(value, dict) else value}")
    return 0


def _signature_validate(args: argparse.Namespace) -> int:
    try:
        signatures = list_signatures(args.pdf)
    except PdfSignatureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    results = []
    for index, signature in enumerate(signatures, start=1):
        result = {
            "order": index,
            "name": signature.display_name,
            "time": _compact_signature_time(signature),
            "cms_parsed": signature.cms_parse_error is None,
            "has_signer_certificate": signature.signer_certificate is not None,
            "has_certificate_chain": bool(signature.certificate_chain),
            "has_embedded_timestamp": signature.embedded_timestamp,
            "covers_entire_file": signature.covers_entire_file,
            "has_later_revisions": signature.has_later_revisions,
            "trust_validated": False,
            "notes": "Cryptographic trust, revocation, and timestamp authority validation are not implemented yet.",
        }
        results.append(result)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for result in results:
            print(f"{result['order']}\t{result['name'] or '-'}\t{result['time']}")
            print(f"  CMS parsed: {_format_bool(result['cms_parsed'])}")
            print(f"  Certificate: {_format_bool(result['has_signer_certificate'])}")
            print(f"  Chain embedded: {_format_bool(result['has_certificate_chain'])}")
            print(f"  Timestamp: {_format_bool(result['has_embedded_timestamp'])}")
            print(f"  Trust validated: no")
    return 0


def _run_file_command(action: object, output: Path) -> int:
    try:
        action()
    except (PdfToolError, PdfInspectionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(output)
    return 0


def _signature_check(args: argparse.Namespace) -> int:
    try:
        signatures = list_signatures(args.pdf)
    except PdfSignatureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([signature.to_dict() for signature in signatures], indent=2))
        return 0

    if args.names_times:
        for index, signature in enumerate(signatures, start=1):
            name = signature.display_name or signature.pdf_signer_name or "-"
            time = _compact_signature_time(signature)
            print(f"{index}\t{name}\t{time}")
        return 0

    if not signatures:
        print("No digital signatures found.")
        return 0

    for index, signature in enumerate(signatures, start=1):
        print(f"Signature {index}")
        print(f"  Field:      {signature.field_name or '-'}")
        print(f"  Signed by:  {signature.display_name or '-'}")
        print(f"  PDF name:   {signature.pdf_signer_name or '-'}")
        print(f"  Cert name:  {signature.certificate_signer_name or '-'}")
        print(f"  Date:       {signature.signing_time or '-'}")
        print(f"  ISO Date:   {signature.signing_time_iso or '-'}")
        print(f"  Reason:     {signature.reason or '-'}")
        print(f"  Location:   {signature.location or '-'}")
        print(f"  Contact:    {signature.contact_info or '-'}")
        print(f"  Page:       {signature.field_page or '-'}")
        print(f"  Filter:     {signature.filter_name or '-'}")
        print(f"  SubFilter:  {signature.subfilter or '-'}")
        print(f"  ByteRange:  {signature.byte_range or '-'}")
        print(f"  File size:  {signature.file_size} bytes")
        print(f"  Revision:   {signature.signed_revision_size or '-'} bytes")
        print(f"  Covered:    {signature.covered_bytes or '-'} bytes")
        print(f"  Container:  {_format_container(signature)}")
        print(f"  Contents:   {_format_bytes(signature.signature_contents_size)}")
        print(f"  Final rev:  {_format_bool(signature.covers_entire_file)}")
        print(f"  Later revs: {_format_bool(signature.has_later_revisions)}")
        print(f"  CMS type:   {signature.cms_content_type or '-'}")
        print(f"  Digest:     {', '.join(signature.cms_digest_algorithms) or '-'}")
        print(f"  Signer alg: {signature.signer_signature_algorithm or '-'}")
        print(f"  Timestamp:  {_format_bool(signature.embedded_timestamp)}")
        print(f"  TS time:    {signature.timestamp_time or '-'}")
        if signature.signer_certificate:
            certificate = signature.signer_certificate
            print("  Certificate:")
            print(f"    Subject:  {certificate.subject or '-'}")
            print(f"    Issuer:   {certificate.issuer or '-'}")
            print(f"    Valid:    {certificate.valid_from or '-'} to {certificate.valid_to or '-'}")
            print(f"    Usage:    {', '.join(certificate.key_usage) or '-'}")
            print(f"    Ext usage:{', '.join(certificate.extended_key_usage) or '-'}")
        if signature.certificate_chain:
            print("  Chain:")
            for chain_index, certificate in enumerate(signature.certificate_chain, start=1):
                print(f"    {chain_index}. {certificate.subject_common_name or certificate.subject or '-'}")
        if signature.cms_parse_error:
            print(f"  CMS error:  {signature.cms_parse_error}")
        print(f"  Object:     {signature.signature_object or '-'}")
        print()

    return 0


def _format_container(signature: object) -> str:
    offset = getattr(signature, "signature_container_offset")
    size = getattr(signature, "signature_container_size")
    if offset is None or size is None:
        return "-"
    return f"offset {offset}, {size} bytes"


def _format_bytes(value: int | None) -> str:
    return f"{value} bytes" if value is not None else "-"


def _format_bool(value: bool | None) -> str:
    if value is None:
        return "-"
    return "yes" if value else "no"


def _format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:.2f}"


def _format_box(box: object) -> str:
    return (
        f"[{_format_number(getattr(box, 'left'))}, "
        f"{_format_number(getattr(box, 'bottom'))}, "
        f"{_format_number(getattr(box, 'right'))}, "
        f"{_format_number(getattr(box, 'top'))}]"
    )


def _compact_signature_time(signature: object) -> str:
    value = (
        getattr(signature, "signing_time_iso")
        or getattr(signature, "timestamp_time")
        or getattr(signature, "signing_time")
    )
    if not value:
        return "-"
    return _local_iso(value)


def _local_iso(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        return value
    return parsed.astimezone().isoformat()
