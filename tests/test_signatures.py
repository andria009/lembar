from __future__ import annotations

from pathlib import Path
import unittest

from lembar.signatures import list_signatures


class SignatureListingTests(unittest.TestCase):
    def test_lists_signature_field_with_indirect_signature(self) -> None:
        pdf = Path(self._testMethodName + ".pdf")
        self.addCleanup(pdf.unlink, missing_ok=True)
        pdf.write_bytes(
            b"""%PDF-1.7
1 0 obj
<< /Type /Catalog /Pages 5 0 R /AcroForm 2 0 R >>
endobj
2 0 obj
<< /Fields [3 0 R] >>
endobj
3 0 obj
<< /FT /Sig /T (Approval Signature) /V 4 0 R >>
endobj
4 0 obj
<<
  /Type /Sig
  /Filter /Adobe.PPKLite
  /SubFilter /adbe.pkcs7.detached
  /Name (Ada Lovelace)
  /M (D:20260430113500+07'00')
  /Reason (Approved)
  /Location (Jakarta)
  /ContactInfo (ada@example.test)
  /ByteRange [0 120 220 30]
  /Contents <00112233>
>>
endobj
5 0 obj
<< /Type /Pages /Kids [6 0 R] /Count 1 >>
endobj
6 0 obj
<< /Type /Page /Annots [3 0 R] >>
endobj
trailer
<< /Root 1 0 R >>
%%EOF
"""
        )

        signatures = list_signatures(pdf)

        self.assertEqual(len(signatures), 1)
        signature = signatures[0]
        self.assertEqual(signature.field_name, "Approval Signature")
        self.assertEqual(signature.field_page, 1)
        self.assertEqual(signature.display_name, "Ada Lovelace")
        self.assertEqual(signature.signer_name, "Ada Lovelace")
        self.assertEqual(signature.pdf_signer_name, "Ada Lovelace")
        self.assertIsNone(signature.certificate_signer_name)
        self.assertEqual(signature.signing_time, "D:20260430113500+07'00'")
        self.assertEqual(signature.signing_time_iso, "2026-04-30T11:35:00+07:00")
        self.assertEqual(signature.reason, "Approved")
        self.assertEqual(signature.location, "Jakarta")
        self.assertEqual(signature.contact_info, "ada@example.test")
        self.assertEqual(signature.filter_name, "Adobe.PPKLite")
        self.assertEqual(signature.subfilter, "adbe.pkcs7.detached")
        self.assertEqual(signature.byte_range, [0, 120, 220, 30])
        self.assertEqual(signature.signed_revision_size, 250)
        self.assertEqual(signature.covered_bytes, 150)
        self.assertEqual(signature.signature_container_offset, 120)
        self.assertEqual(signature.signature_container_size, 100)
        self.assertEqual(signature.signature_contents_size, 4)
        self.assertFalse(signature.covers_entire_file)
        self.assertTrue(signature.has_later_revisions)
        self.assertTrue(signature.document_modified_after_signature)
        self.assertEqual(signature.signature_object, "4 0 R")
        self.assertEqual(signature.field_object, "3 0 R")

    def test_lists_unreferenced_signature_dictionary(self) -> None:
        pdf = Path(self._testMethodName + ".pdf")
        self.addCleanup(pdf.unlink, missing_ok=True)
        pdf.write_bytes(
            b"""%PDF-1.7
1 0 obj
<< /Type /Sig /Name <FEFF004A0061006E0065> /Filter /ETSI.CAdES.detached >>
endobj
%%EOF
"""
        )

        signatures = list_signatures(pdf)

        self.assertEqual(len(signatures), 1)
        self.assertEqual(signatures[0].signer_name, "Jane")
        self.assertEqual(signatures[0].filter_name, "ETSI.CAdES.detached")
        self.assertEqual(signatures[0].signature_object, "1 0 R")

    def test_returns_empty_list_when_no_signatures(self) -> None:
        pdf = Path(self._testMethodName + ".pdf")
        self.addCleanup(pdf.unlink, missing_ok=True)
        pdf.write_bytes(
            b"""%PDF-1.7
1 0 obj
<< /Type /Catalog >>
endobj
%%EOF
"""
        )

        self.assertEqual(list_signatures(pdf), [])


if __name__ == "__main__":
    unittest.main()
