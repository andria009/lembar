"""Structural and CMS/CAdES digital signature inspection for PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import hashlib
from pathlib import Path
import re
from typing import Any

from asn1crypto import algos, cms, core, tsp, x509


class PdfSignatureError(Exception):
    """Raised when a PDF cannot be inspected for signatures."""


@dataclass(frozen=True)
class PdfRef:
    """Indirect object reference such as `79 0 R`."""

    object_number: int
    generation: int

    def label(self) -> str:
        return f"{self.object_number} {self.generation} R"


@dataclass(frozen=True)
class PdfName:
    """PDF name object without the leading slash."""

    value: str


@dataclass(frozen=True)
class PdfCertificate:
    """Flattened X.509 certificate details safe to expose in JSON output."""

    subject: str | None
    subject_common_name: str | None
    subject_organization: str | None
    issuer: str | None
    issuer_common_name: str | None
    issuer_organization: str | None
    serial_number: str | None
    valid_from: str | None
    valid_to: str | None
    key_usage: list[str]
    extended_key_usage: list[str]
    sha1_fingerprint: str | None
    sha256_fingerprint: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "subject_common_name": self.subject_common_name,
            "subject_organization": self.subject_organization,
            "issuer": self.issuer,
            "issuer_common_name": self.issuer_common_name,
            "issuer_organization": self.issuer_organization,
            "serial_number": self.serial_number,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "key_usage": self.key_usage,
            "extended_key_usage": self.extended_key_usage,
            "sha1_fingerprint": self.sha1_fingerprint,
            "sha256_fingerprint": self.sha256_fingerprint,
        }


@dataclass(frozen=True)
class PdfSignature:
    """Combined PDF signature field, byte-range, and CMS certificate details."""

    field_name: str | None
    field_page: int | None
    display_name: str | None
    signer_name: str | None
    pdf_signer_name: str | None
    certificate_signer_name: str | None
    signing_time: str | None
    signing_time_iso: str | None
    reason: str | None
    location: str | None
    contact_info: str | None
    filter_name: str | None
    subfilter: str | None
    byte_range: list[int] | None
    file_size: int
    signed_revision_size: int | None
    covered_bytes: int | None
    signature_container_offset: int | None
    signature_container_size: int | None
    signature_contents_size: int | None
    covers_entire_file: bool | None
    has_later_revisions: bool | None
    document_modified_after_signature: bool | None
    cms_content_type: str | None
    cms_digest_algorithms: list[str]
    signer_digest_algorithm: str | None
    signer_signature_algorithm: str | None
    embedded_timestamp: bool | None
    timestamp_time: str | None
    signer_certificate: PdfCertificate | None
    certificate_chain: list[PdfCertificate]
    certificates: list[PdfCertificate]
    cms_parse_error: str | None
    signature_object: str | None
    field_object: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "field_page": self.field_page,
            "display_name": self.display_name,
            "signer_name": self.signer_name,
            "pdf_signer_name": self.pdf_signer_name,
            "certificate_signer_name": self.certificate_signer_name,
            "signing_time": self.signing_time,
            "signing_time_iso": self.signing_time_iso,
            "reason": self.reason,
            "location": self.location,
            "contact_info": self.contact_info,
            "filter": self.filter_name,
            "subfilter": self.subfilter,
            "byte_range": self.byte_range,
            "file_size": self.file_size,
            "signed_revision_size": self.signed_revision_size,
            "covered_bytes": self.covered_bytes,
            "signature_container_offset": self.signature_container_offset,
            "signature_container_size": self.signature_container_size,
            "signature_contents_size": self.signature_contents_size,
            "covers_entire_file": self.covers_entire_file,
            "has_later_revisions": self.has_later_revisions,
            "document_modified_after_signature": self.document_modified_after_signature,
            "cms_content_type": self.cms_content_type,
            "cms_digest_algorithms": self.cms_digest_algorithms,
            "signer_digest_algorithm": self.signer_digest_algorithm,
            "signer_signature_algorithm": self.signer_signature_algorithm,
            "embedded_timestamp": self.embedded_timestamp,
            "timestamp_time": self.timestamp_time,
            "signer_certificate": self.signer_certificate.to_dict() if self.signer_certificate else None,
            "certificate_chain": [certificate.to_dict() for certificate in self.certificate_chain],
            "certificates": [certificate.to_dict() for certificate in self.certificates],
            "cms_parse_error": self.cms_parse_error,
            "signature_object": self.signature_object,
            "field_object": self.field_object,
        }


_OBJECT_RE = re.compile(
    rb"(?m)(\d+)\s+(\d+)\s+obj\b(?P<body>.*?)\bendobj\b",
    re.DOTALL,
)


class _PdfParser:
    """Small PDF object parser tuned for signature dictionaries.

    This is not a full PDF parser. It reads indirect objects well enough to
    locate AcroForm signature fields and signature dictionaries, including the
    `/Contents` value that carries the CMS/CAdES signature container.
    """

    def __init__(self, data: bytes) -> None:
        self.objects: dict[PdfRef, Any] = {}
        for match in _OBJECT_RE.finditer(data):
            ref = PdfRef(int(match.group(1)), int(match.group(2)))
            body = match.group("body")
            parsed = _parse_pdf_value(_before_stream(body))
            if parsed is not None:
                self.objects[ref] = parsed

    def resolve(self, value: Any) -> Any:
        if isinstance(value, PdfRef):
            return self.objects.get(value)
        return value


class _Tokenizer:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0

    def peek(self) -> str | bytes | None:
        current = self.position
        token = self.next()
        self.position = current
        return token

    def next(self) -> str | bytes | None:
        self._skip_noise()
        if self.position >= len(self.data):
            return None

        if self.data.startswith(b"<<", self.position):
            self.position += 2
            return "<<"
        if self.data.startswith(b">>", self.position):
            self.position += 2
            return ">>"

        char = self.data[self.position : self.position + 1]
        if char in b"[]":
            self.position += 1
            return char.decode("ascii")
        if char == b"/":
            return self._read_name()
        if char == b"(":
            return self._read_literal_string()
        if char == b"<":
            return self._read_hex_string()

        start = self.position
        while self.position < len(self.data):
            char = self.data[self.position : self.position + 1]
            if char.isspace() or char in b"[]<>()/%":
                break
            self.position += 1
        return self.data[start : self.position].decode("latin-1")

    def _skip_noise(self) -> None:
        while self.position < len(self.data):
            char = self.data[self.position : self.position + 1]
            if char.isspace():
                self.position += 1
                continue
            if char == b"%":
                while self.position < len(self.data) and self.data[self.position : self.position + 1] not in b"\r\n":
                    self.position += 1
                continue
            break

    def _read_name(self) -> PdfName:
        self.position += 1
        start = self.position
        while self.position < len(self.data):
            char = self.data[self.position : self.position + 1]
            if char.isspace() or char in b"[]<>()/%":
                break
            self.position += 1
        raw = self.data[start : self.position].decode("latin-1")
        return PdfName(_decode_name(raw))

    def _read_literal_string(self) -> str:
        self.position += 1
        depth = 1
        output = bytearray()
        while self.position < len(self.data) and depth:
            char = self.data[self.position]
            self.position += 1
            if char == 0x5C:
                if self.position >= len(self.data):
                    break
                escaped = self.data[self.position]
                self.position += 1
                output.extend(_decode_escape(escaped))
                continue
            if char == 0x28:
                depth += 1
            elif char == 0x29:
                depth -= 1
                if depth == 0:
                    break
            output.append(char)
        return output.decode("utf-8", errors="replace")

    def _read_hex_string(self) -> bytes:
        self.position += 1
        start = self.position
        while self.position < len(self.data) and self.data[self.position : self.position + 1] != b">":
            self.position += 1
        raw = re.sub(rb"\s+", b"", self.data[start : self.position])
        if self.position < len(self.data):
            self.position += 1
        if len(raw) % 2:
            raw += b"0"
        try:
            return bytes.fromhex(raw.decode("ascii"))
        except ValueError:
            return raw


def list_signatures(path: str | Path) -> list[PdfSignature]:
    """Return all signature fields and standalone signature dictionaries."""
    pdf_path = Path(path)
    if not pdf_path.exists():
        raise PdfSignatureError(f"file not found: {pdf_path}")
    if not pdf_path.is_file():
        raise PdfSignatureError(f"not a file: {pdf_path}")

    data = pdf_path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise PdfSignatureError("file does not look like a PDF")

    parser = _PdfParser(data)
    annotation_pages = _annotation_pages(parser)
    signatures: list[PdfSignature] = []
    seen_signature_refs: set[PdfRef] = set()

    for field_ref, field in parser.objects.items():
        if not isinstance(field, dict) or _name_value(field.get("FT")) != "Sig":
            continue

        signature_value = field.get("V")
        signature_ref = signature_value if isinstance(signature_value, PdfRef) else None
        signature_dict = parser.resolve(signature_value)
        signatures.append(
            _build_signature(
                signature_dict if isinstance(signature_dict, dict) else None,
                signature_ref,
                field,
                field_ref,
                annotation_pages.get(field_ref),
                len(data),
            )
        )
        if signature_ref is not None:
            seen_signature_refs.add(signature_ref)

    for signature_ref, signature_dict in parser.objects.items():
        if signature_ref in seen_signature_refs:
            continue
        if isinstance(signature_dict, dict) and _name_value(signature_dict.get("Type")) == "Sig":
            signatures.append(_build_signature(signature_dict, signature_ref, None, None, None, len(data)))

    return signatures


def _build_signature(
    signature_dict: dict[str, Any] | None,
    signature_ref: PdfRef | None,
    field: dict[str, Any] | None,
    field_ref: PdfRef | None,
    field_page: int | None,
    file_size: int,
) -> PdfSignature:
    signature_dict = signature_dict or {}
    byte_range = _integer_list(signature_dict.get("ByteRange"))
    byte_range_details = _byte_range_details(byte_range, file_size)
    signing_time = _text(signature_dict.get("M"))
    signature_contents = signature_dict.get("Contents")
    cms_details = _cms_details(signature_contents)
    pdf_signer_name = _text(signature_dict.get("Name"))
    certificate_signer_name = _certificate_display_name(cms_details["signer_certificate"])
    display_name = certificate_signer_name or pdf_signer_name
    return PdfSignature(
        field_name=_text(field.get("T")) if field else None,
        field_page=field_page,
        display_name=display_name,
        signer_name=display_name,
        pdf_signer_name=pdf_signer_name,
        certificate_signer_name=certificate_signer_name,
        signing_time=signing_time,
        signing_time_iso=_parse_pdf_date(signing_time),
        reason=_text(signature_dict.get("Reason")),
        location=_text(signature_dict.get("Location")),
        contact_info=_text(signature_dict.get("ContactInfo")),
        filter_name=_name_value(signature_dict.get("Filter")),
        subfilter=_name_value(signature_dict.get("SubFilter")),
        byte_range=byte_range,
        file_size=file_size,
        signed_revision_size=byte_range_details["signed_revision_size"],
        covered_bytes=byte_range_details["covered_bytes"],
        signature_container_offset=byte_range_details["signature_container_offset"],
        signature_container_size=byte_range_details["signature_container_size"],
        signature_contents_size=_contents_size(signature_contents),
        covers_entire_file=byte_range_details["covers_entire_file"],
        has_later_revisions=byte_range_details["has_later_revisions"],
        document_modified_after_signature=byte_range_details["document_modified_after_signature"],
        cms_content_type=cms_details["content_type"],
        cms_digest_algorithms=cms_details["digest_algorithms"],
        signer_digest_algorithm=cms_details["signer_digest_algorithm"],
        signer_signature_algorithm=cms_details["signer_signature_algorithm"],
        embedded_timestamp=cms_details["embedded_timestamp"],
        timestamp_time=cms_details["timestamp_time"],
        signer_certificate=cms_details["signer_certificate"],
        certificate_chain=cms_details["certificate_chain"],
        certificates=cms_details["certificates"],
        cms_parse_error=cms_details["parse_error"],
        signature_object=signature_ref.label() if signature_ref else None,
        field_object=field_ref.label() if field_ref else None,
    )


def _parse_pdf_value(data: bytes) -> Any:
    tokenizer = _Tokenizer(data)
    return _parse_value(tokenizer)


def _parse_value(tokenizer: _Tokenizer) -> Any:
    token = tokenizer.next()
    if token is None:
        return None
    if token == "<<":
        values: dict[str, Any] = {}
        while tokenizer.peek() not in (None, ">>"):
            key = tokenizer.next()
            if not isinstance(key, PdfName):
                break
            values[key.value] = _parse_value(tokenizer)
        tokenizer.next()
        return values
    if token == "[":
        values: list[Any] = []
        while tokenizer.peek() not in (None, "]"):
            values.append(_parse_value(tokenizer))
        tokenizer.next()
        return values
    if isinstance(token, PdfName | bytes):
        return token
    if token in ("true", "false"):
        return token == "true"
    if token == "null":
        return None
    if _is_number(token):
        first = _number(token)
        position = tokenizer.position
        second_token = tokenizer.next()
        third_token = tokenizer.next()
        if (
            isinstance(first, int)
            and isinstance(second_token, str)
            and _is_integer(second_token)
            and third_token == "R"
        ):
            return PdfRef(first, int(second_token))
        tokenizer.position = position
        return first
    return token


def _before_stream(body: bytes) -> bytes:
    marker = re.search(rb"\bstream\b", body)
    return body[: marker.start()] if marker else body


def _decode_name(raw: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    return re.sub(r"#([0-9A-Fa-f]{2})", replace, raw)


def _decode_escape(value: int) -> bytes:
    escapes = {
        ord("n"): b"\n",
        ord("r"): b"\r",
        ord("t"): b"\t",
        ord("b"): b"\b",
        ord("f"): b"\f",
        ord("("): b"(",
        ord(")"): b")",
        ord("\\"): b"\\",
    }
    return escapes.get(value, bytes([value]))


def _is_integer(value: str) -> bool:
    return bool(re.fullmatch(r"[+-]?\d+", value))


def _is_number(value: str) -> bool:
    return bool(re.fullmatch(r"[+-]?(?:\d+|\d*\.\d+)", value))


def _number(value: str) -> int | float:
    return int(value) if _is_integer(value) else float(value)


def _name_value(value: Any) -> str | None:
    return value.value if isinstance(value, PdfName) else None


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        if value.startswith(b"\xfe\xff"):
            return value[2:].decode("utf-16-be", errors="replace").rstrip("\x00")
        return value.decode("utf-8", errors="replace").rstrip("\x00")
    if isinstance(value, PdfName):
        return value.value
    return None


def _integer_list(value: Any) -> list[int] | None:
    if not isinstance(value, list):
        return None
    integers: list[int] = []
    for item in value:
        if not isinstance(item, int):
            return None
        integers.append(item)
    return integers


def _annotation_pages(parser: _PdfParser) -> dict[PdfRef, int]:
    """Map annotation object references to 1-based page numbers."""
    catalog = next(
        (obj for obj in parser.objects.values() if isinstance(obj, dict) and _name_value(obj.get("Type")) == "Catalog"),
        None,
    )
    if not isinstance(catalog, dict):
        return {}

    pages_ref = catalog.get("Pages")
    pages: dict[PdfRef, int] = {}
    page_number = 0

    def walk(node_ref: Any) -> None:
        nonlocal page_number
        node = parser.resolve(node_ref)
        if not isinstance(node, dict):
            return
        node_type = _name_value(node.get("Type"))
        if node_type == "Page":
            page_number += 1
            for annotation_ref in _references(node.get("Annots")):
                pages[annotation_ref] = page_number
            return
        for kid_ref in _references(node.get("Kids")):
            walk(kid_ref)

    walk(pages_ref)
    return pages


def _references(value: Any) -> list[PdfRef]:
    if isinstance(value, PdfRef):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, PdfRef)]
    return []


def _byte_range_details(byte_range: list[int] | None, file_size: int) -> dict[str, int | bool | None]:
    """Summarize the signed byte ranges and revision coverage."""
    empty = {
        "signed_revision_size": None,
        "covered_bytes": None,
        "signature_container_offset": None,
        "signature_container_size": None,
        "covers_entire_file": None,
        "has_later_revisions": None,
        "document_modified_after_signature": None,
    }
    if byte_range is None or len(byte_range) != 4:
        return empty

    first_offset, first_length, second_offset, second_length = byte_range
    first_end = first_offset + first_length
    signed_revision_size = second_offset + second_length
    covers_entire_file = signed_revision_size == file_size
    has_later_revisions = signed_revision_size < file_size
    return {
        "signed_revision_size": signed_revision_size,
        "covered_bytes": first_length + second_length,
        "signature_container_offset": first_end,
        "signature_container_size": max(0, second_offset - first_end),
        "covers_entire_file": covers_entire_file,
        "has_later_revisions": has_later_revisions,
        "document_modified_after_signature": has_later_revisions,
    }


def _contents_size(value: Any) -> int | None:
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    return None


def _parse_pdf_date(value: str | None) -> str | None:
    """Parse a standard PDF date string into ISO 8601 when possible."""
    if value is None or not value.startswith("D:"):
        return None

    match = re.fullmatch(
        r"D:(?P<year>\d{4})"
        r"(?P<month>\d{2})?"
        r"(?P<day>\d{2})?"
        r"(?P<hour>\d{2})?"
        r"(?P<minute>\d{2})?"
        r"(?P<second>\d{2})?"
        r"(?P<offset>Z|[+-]\d{2}'?\d{2}'?)?",
        value,
    )
    if not match:
        return None

    parts = match.groupdict()
    year = int(parts["year"])
    month = int(parts["month"] or "01")
    day = int(parts["day"] or "01")
    hour = int(parts["hour"] or "00")
    minute = int(parts["minute"] or "00")
    second = int(parts["second"] or "00")
    offset = parts["offset"]

    tzinfo = None
    if offset == "Z":
        tzinfo = timezone.utc
    elif offset:
        sign = 1 if offset[0] == "+" else -1
        offset_digits = re.sub(r"\D", "", offset[1:])
        hours = int(offset_digits[:2])
        minutes = int(offset_digits[2:4] or "00")
        tzinfo = timezone(sign * timedelta(hours=hours, minutes=minutes))

    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=tzinfo).isoformat()
    except ValueError:
        return None


def _cms_details(value: Any) -> dict[str, Any]:
    """Parse the CMS/CAdES signature container embedded in `/Contents`."""
    empty = {
        "content_type": None,
        "digest_algorithms": [],
        "signer_digest_algorithm": None,
        "signer_signature_algorithm": None,
        "embedded_timestamp": None,
        "timestamp_time": None,
        "signer_certificate": None,
        "certificate_chain": [],
        "certificates": [],
        "parse_error": None,
    }
    if not isinstance(value, bytes) or not value:
        return empty

    try:
        der = _der_payload(value)
        content_info = cms.ContentInfo.load(der, strict=False)
        content_type = content_info["content_type"].native
        if content_type != "signed_data":
            return {**empty, "content_type": content_type}

        signed_data = content_info["content"]
        certificates = _extract_certificates(signed_data)
        signer_info = _first_signer_info(signed_data)
        signer_certificate = _find_signer_certificate(signer_info, certificates)
        certificate_chain = _certificate_chain(signer_certificate, certificates)

        timestamp_time = _timestamp_time(signer_info)
        return {
            "content_type": content_type,
            "digest_algorithms": _algorithm_names(signed_data["digest_algorithms"]),
            "signer_digest_algorithm": _algorithm_name(signer_info["digest_algorithm"]) if signer_info else None,
            "signer_signature_algorithm": _algorithm_name(signer_info["signature_algorithm"]) if signer_info else None,
            "embedded_timestamp": _has_timestamp(signer_info),
            "timestamp_time": timestamp_time,
            "signer_certificate": _certificate_details(signer_certificate) if signer_certificate else None,
            "certificate_chain": [_certificate_details(certificate) for certificate in certificate_chain],
            "certificates": [_certificate_details(certificate) for certificate in certificates],
            "parse_error": None,
        }
    except Exception as exc:  # noqa: BLE001 - malformed CMS should not hide PDF-level details.
        return {**empty, "parse_error": str(exc)}


def _der_payload(value: bytes) -> bytes:
    """Trim placeholder padding without breaking BER indefinite-length data."""
    if len(value) >= 2 and value[1] == 0x80:
        # BER indefinite-length containers end with `00 00`; those bytes are
        # syntax, not PDF placeholder padding. Stripping them breaks parsing.
        return value

    stripped = value.rstrip(b"\x00")
    if len(stripped) < 2:
        return value

    total_length = _der_total_length(stripped)
    if total_length is None:
        return stripped
    return stripped[:total_length]


def _der_total_length(value: bytes) -> int | None:
    if len(value) < 2:
        return None
    first_length = value[1]
    if first_length < 0x80:
        return 2 + first_length

    length_size = first_length & 0x7F
    if length_size == 0 or len(value) < 2 + length_size:
        return None
    payload_length = int.from_bytes(value[2 : 2 + length_size], "big")
    return 2 + length_size + payload_length


def _extract_certificates(signed_data: cms.SignedData) -> list[x509.Certificate]:
    certificate_set = signed_data["certificates"]
    if certificate_set.native is None:
        return []

    certificates: list[x509.Certificate] = []
    for choice in certificate_set:
        if choice.name == "certificate":
            certificates.append(choice.chosen)
    return certificates


def _first_signer_info(signed_data: cms.SignedData) -> cms.SignerInfo | None:
    signer_infos = signed_data["signer_infos"]
    if not signer_infos:
        return None
    return signer_infos[0]


def _find_signer_certificate(
    signer_info: cms.SignerInfo | None,
    certificates: list[x509.Certificate],
) -> x509.Certificate | None:
    """Find the certificate that corresponds to the first CMS signer info."""
    if signer_info is None:
        return None

    signed_attribute_certificate = _find_signer_certificate_from_signed_attributes(signer_info, certificates)
    if signed_attribute_certificate is not None:
        return signed_attribute_certificate

    sid = signer_info["sid"]
    if sid.name == "issuer_and_serial_number":
        issuer_and_serial = sid.chosen
        serial_number = issuer_and_serial["serial_number"].native
        issuer = issuer_and_serial["issuer"].dump()
        for certificate in certificates:
            if certificate.serial_number == serial_number and certificate.issuer.dump() == issuer:
                return certificate
    elif sid.name == "subject_key_identifier":
        key_identifier = sid.chosen.native
        for certificate in certificates:
            extension_value = _extension_value(certificate, "key_identifier")
            if extension_value == key_identifier:
                return certificate
    return certificates[0] if certificates else None


def _find_signer_certificate_from_signed_attributes(
    signer_info: cms.SignerInfo,
    certificates: list[x509.Certificate],
) -> x509.Certificate | None:
    """Match CAdES signing-certificate attributes to embedded certificates."""
    signing_certificate_hashes = _signing_certificate_hashes(signer_info)
    for algorithm, expected_hash in signing_certificate_hashes:
        for certificate in certificates:
            if _digest(certificate.dump(), algorithm) == expected_hash:
                return certificate
    return None


def _signing_certificate_hashes(signer_info: cms.SignerInfo) -> list[tuple[str, bytes]]:
    """Read ESSCertID / ESSCertIDv2 hashes from signed attributes."""
    signed_attrs = signer_info["signed_attrs"]
    if signed_attrs.native is None:
        return []

    hashes: list[tuple[str, bytes]] = []
    for attribute in signed_attrs:
        oid = attribute["type"].dotted
        if oid == "1.2.840.113549.1.9.16.2.12":
            hashes.extend(_signing_certificate_v1_hashes(attribute))
        elif oid == "1.2.840.113549.1.9.16.2.47":
            hashes.extend(_signing_certificate_v2_hashes(attribute))
    return hashes


def _signing_certificate_v1_hashes(attribute: cms.CMSAttribute) -> list[tuple[str, bytes]]:
    hashes: list[tuple[str, bytes]] = []
    for value in attribute["values"]:
        signing_certificate = core.Sequence.load(value.dump(), strict=False)
        certs = signing_certificate[0]
        for cert_id in certs:
            hashes.append(("sha1", cert_id[0].native))
    return hashes


def _signing_certificate_v2_hashes(attribute: cms.CMSAttribute) -> list[tuple[str, bytes]]:
    hashes: list[tuple[str, bytes]] = []
    for value in attribute["values"]:
        signing_certificate = core.Sequence.load(value.dump(), strict=False)
        certs = signing_certificate[0]
        for cert_id in certs:
            if len(cert_id) > 1 and isinstance(cert_id[0], core.Sequence):
                algorithm = algos.DigestAlgorithm.load(cert_id[0].dump(), strict=False)["algorithm"].native
                cert_hash = cert_id[1].native
            else:
                algorithm = "sha256"
                cert_hash = cert_id[0].native
            hashes.append((algorithm, cert_hash))
    return hashes


def _certificate_chain(
    signer_certificate: x509.Certificate | None,
    certificates: list[x509.Certificate],
) -> list[x509.Certificate]:
    """Build an embedded certificate chain from signer to root when possible."""
    if signer_certificate is None:
        return []

    ordered = [signer_certificate]
    current = signer_certificate
    used = {current.dump()}
    while current.subject.dump() != current.issuer.dump():
        issuer = next(
            (
                certificate
                for certificate in certificates
                if certificate.subject.dump() == current.issuer.dump() and certificate.dump() not in used
            ),
            None,
        )
        if issuer is None:
            break
        ordered.append(issuer)
        used.add(issuer.dump())
        current = issuer
    return ordered


def _certificate_details(certificate: x509.Certificate) -> PdfCertificate:
    return PdfCertificate(
        subject=certificate.subject.human_friendly,
        subject_common_name=_name_attribute(certificate.subject, "common_name"),
        subject_organization=_name_attribute(certificate.subject, "organization_name"),
        issuer=certificate.issuer.human_friendly,
        issuer_common_name=_name_attribute(certificate.issuer, "common_name"),
        issuer_organization=_name_attribute(certificate.issuer, "organization_name"),
        serial_number=str(certificate.serial_number),
        valid_from=_datetime_to_iso(certificate["tbs_certificate"]["validity"]["not_before"].native),
        valid_to=_datetime_to_iso(certificate["tbs_certificate"]["validity"]["not_after"].native),
        key_usage=_list_extension(certificate, "key_usage"),
        extended_key_usage=_list_extension(certificate, "extended_key_usage"),
        sha1_fingerprint=_fingerprint(certificate, "sha1"),
        sha256_fingerprint=_fingerprint(certificate, "sha256"),
    )


def _certificate_display_name(certificate: PdfCertificate | None) -> str | None:
    if certificate is None:
        return None
    return certificate.subject_common_name or certificate.subject_organization or certificate.subject


def _name_attribute(name: x509.Name, key: str) -> str | None:
    value = name.native.get(key)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if value is None:
        return None
    return str(value)


def _list_extension(certificate: x509.Certificate, extension_name: str) -> list[str]:
    value = _extension_value(certificate, extension_name)
    if value is None:
        return []
    if isinstance(value, set | list | tuple):
        return sorted(str(item) for item in value)
    return [str(value)]


def _extension_value(certificate: x509.Certificate, extension_name: str) -> Any:
    extensions = certificate["tbs_certificate"]["extensions"]
    if extensions.native is None:
        return None
    for extension in extensions:
        if extension["extn_id"].native == extension_name:
            return extension["extn_value"].native
    return None


def _fingerprint(certificate: x509.Certificate, algorithm: str) -> str | None:
    try:
        if algorithm == "sha1":
            return _colon_hex(certificate.sha1_fingerprint)
        if algorithm == "sha256":
            return _colon_hex(certificate.sha256_fingerprint)
    except Exception:
        return None
    return None


def _colon_hex(value: str) -> str:
    compact = re.sub(r"[^0-9A-Fa-f]", "", value).upper()
    return ":".join(compact[index : index + 2] for index in range(0, len(compact), 2))


def _digest(value: bytes, algorithm: str) -> bytes | None:
    try:
        return hashlib.new(algorithm.replace("-", ""), value).digest()
    except ValueError:
        return None


def _datetime_to_iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _algorithm_names(values: Any) -> list[str]:
    return [_algorithm_name(value) for value in values if _algorithm_name(value)]


def _algorithm_name(value: Any) -> str | None:
    try:
        return value["algorithm"].native
    except Exception:
        return None


def _has_timestamp(signer_info: cms.SignerInfo | None) -> bool | None:
    if signer_info is None:
        return None
    return _timestamp_attribute(signer_info) is not None


def _timestamp_time(signer_info: cms.SignerInfo | None) -> str | None:
    """Return the embedded RFC 3161 timestamp generation time when present."""
    timestamp_attribute = _timestamp_attribute(signer_info)
    if timestamp_attribute is None:
        return None

    try:
        token = timestamp_attribute["values"][0]
        content_info = token if isinstance(token, cms.ContentInfo) else cms.ContentInfo.load(token.dump(), strict=False)
        signed_data = content_info["content"]
        encap_content_info = signed_data["encap_content_info"]
        content = encap_content_info["content"]
        tst_info = tsp.TSTInfo.load(content.native if isinstance(content.native, bytes) else content.contents)
        return _datetime_to_iso(tst_info["gen_time"].native)
    except Exception:
        return None


def _timestamp_attribute(signer_info: cms.SignerInfo | None) -> Any:
    if signer_info is None:
        return None
    unsigned_attrs = signer_info["unsigned_attrs"]
    if unsigned_attrs.native is None:
        return None
    for attribute in unsigned_attrs:
        if attribute["type"].native == "signature_time_stamp_token":
            return attribute
    return None
