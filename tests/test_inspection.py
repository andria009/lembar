from __future__ import annotations

from pathlib import Path
import unittest

from pypdf import PdfWriter

from lembar.inspection import inspect_pages, inspect_pdf


class PdfInspectionTests(unittest.TestCase):
    def test_inspect_pdf_reports_file_level_info(self) -> None:
        pdf = Path(self._testMethodName + ".pdf")
        self.addCleanup(pdf.unlink, missing_ok=True)
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=300)
        writer.add_metadata({"/Title": "Inspection Sample"})
        with pdf.open("wb") as output:
            writer.write(output)

        info = inspect_pdf(pdf)

        self.assertEqual(info.page_count, 1)
        self.assertFalse(info.encrypted)
        self.assertEqual(info.metadata["Title"], "Inspection Sample")
        self.assertGreater(info.file_size, 0)

    def test_inspect_pages_reports_dimensions_and_rotation(self) -> None:
        pdf = Path(self._testMethodName + ".pdf")
        self.addCleanup(pdf.unlink, missing_ok=True)
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        page.rotate(90)
        with pdf.open("wb") as output:
            writer.write(output)

        pages = inspect_pages(pdf)

        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].page, 1)
        self.assertEqual(pages[0].width, 612)
        self.assertEqual(pages[0].height, 792)
        self.assertEqual(pages[0].rotation, 90)
        self.assertEqual(pages[0].media_box.width, 612)
        self.assertEqual(pages[0].media_box.height, 792)


if __name__ == "__main__":
    unittest.main()
