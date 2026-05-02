from __future__ import annotations

from pathlib import Path
import unittest

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject

from lembar.page_ops import delete_pages, extract_pages, merge_pdfs, reorder_pages, rotate_pages


class PageOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pdf1 = Path(self._testMethodName + "-one.pdf")
        self.pdf2 = Path(self._testMethodName + "-two.pdf")
        self.addCleanup(self.pdf1.unlink, missing_ok=True)
        self.addCleanup(self.pdf2.unlink, missing_ok=True)
        _blank_pdf(self.pdf1, [100, 200])
        _blank_pdf(self.pdf2, [300])

    def test_merge_pdfs(self) -> None:
        output = Path(self._testMethodName + "-merged.pdf")
        self.addCleanup(output.unlink, missing_ok=True)

        signed_inputs = merge_pdfs([self.pdf1, self.pdf2], output)

        self.assertEqual(signed_inputs, [])
        self.assertEqual(len(PdfReader(output).pages), 3)

    def test_merge_pdfs_warns_via_return_and_preserves_attachments(self) -> None:
        signed_pdf = Path(self._testMethodName + "-signed.pdf")
        output = Path(self._testMethodName + "-merged.pdf")
        self.addCleanup(signed_pdf.unlink, missing_ok=True)
        self.addCleanup(output.unlink, missing_ok=True)
        _signature_field_pdf(signed_pdf)

        signed_inputs = merge_pdfs([signed_pdf, self.pdf2], output, preserve_as_attachments=True)

        merged = PdfReader(output)
        self.assertEqual(signed_inputs, [signed_pdf])
        self.assertEqual(len(merged.pages), 2)
        self.assertIn(signed_pdf.name, merged.attachments)

    def test_extract_delete_and_reorder_pages(self) -> None:
        extracted = Path(self._testMethodName + "-extracted.pdf")
        deleted = Path(self._testMethodName + "-deleted.pdf")
        reordered = Path(self._testMethodName + "-reordered.pdf")
        self.addCleanup(extracted.unlink, missing_ok=True)
        self.addCleanup(deleted.unlink, missing_ok=True)
        self.addCleanup(reordered.unlink, missing_ok=True)

        extract_pages(self.pdf1, "2", extracted)
        delete_pages(self.pdf1, "1", deleted)
        reorder_pages(self.pdf1, "2,1", reordered)

        self.assertEqual(float(PdfReader(extracted).pages[0].mediabox.width), 200)
        self.assertEqual(len(PdfReader(deleted).pages), 1)
        self.assertEqual(float(PdfReader(reordered).pages[0].mediabox.width), 200)

    def test_rotate_pages(self) -> None:
        output = Path(self._testMethodName + "-rotated.pdf")
        self.addCleanup(output.unlink, missing_ok=True)

        rotate_pages(self.pdf1, "1", 90, output)

        self.assertEqual(PdfReader(output).pages[0].rotation, 90)


def _blank_pdf(path: Path, widths: list[int]) -> None:
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=400)
    with path.open("wb") as handle:
        writer.write(handle)


def _signature_field_pdf(path: Path) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    signature = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Sig"),
            NameObject("/Name"): TextStringObject("Test Signer"),
            NameObject("/ByteRange"): ArrayObject(
                [NumberObject(0), NumberObject(1), NumberObject(2), NumberObject(3)]
            ),
        }
    )
    signature_ref = writer._add_object(signature)
    field = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Sig"),
            NameObject("/T"): TextStringObject("Signature1"),
            NameObject("/V"): signature_ref,
        }
    )
    field_ref = writer._add_object(field)
    writer._root_object.update(
        {NameObject("/AcroForm"): DictionaryObject({NameObject("/Fields"): ArrayObject([field_ref])})}
    )
    page[NameObject("/Annots")] = ArrayObject([field_ref])
    with path.open("wb") as handle:
        writer.write(handle)


if __name__ == "__main__":
    unittest.main()
