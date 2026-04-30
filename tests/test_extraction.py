from __future__ import annotations

import csv
from io import StringIO
import unittest

from lembar.extraction import _normalized_table, _postprocess_table, _usable_tables


class TableExtractionTests(unittest.TestCase):
    def test_normalized_table_collapses_wrapped_cell_text(self) -> None:
        table = [
            ["No.", "Predikat Kinerja\nPegawai", "Penjelasan"],
            [
                "1",
                "Sangat baik",
                "Hasil kerja pegawai di atas\nEkspektasi dan perilaku kerja\npegawai di atas Ekspektasi",
            ],
        ]

        self.assertEqual(
            _normalized_table(table),
            [
                ["No.", "Predikat Kinerja Pegawai", "Penjelasan"],
                [
                    1,
                    "Sangat baik",
                    "Hasil kerja pegawai di atas Ekspektasi dan perilaku kerja pegawai di atas Ekspektasi",
                ],
            ],
        )

    def test_normalized_table_preserves_empty_cells_as_empty_strings(self) -> None:
        self.assertEqual(_normalized_table([[None, "  A\t B  "]]), [["", "A B"]])

    def test_normalized_table_preserves_numbered_list_breaks(self) -> None:
        table = [
            [
                "2",
                "Baik",
                "1. Hasil kerja pegawai di atas Ekspektasi dan perilaku kerja Pegawai sesuai Ekspektasi.\n"
                "2. Hasil kerja pegawai sesuai Ekspektasi dan perilaku kerja Pegawai sesuai Ekspektasi.\n"
                "3. Hasil kerja pegawai sesuai Ekspektasi dan perilaku kerja Pegawai di atas Ekspektasi.",
            ]
        ]

        self.assertEqual(
            _normalized_table(table),
            [
                [
                    2,
                    "Baik",
                    "1. Hasil kerja pegawai di atas Ekspektasi dan perilaku kerja Pegawai sesuai Ekspektasi. \n"
                    "2. Hasil kerja pegawai sesuai Ekspektasi dan perilaku kerja Pegawai sesuai Ekspektasi. \n"
                    "3. Hasil kerja pegawai sesuai Ekspektasi dan perilaku kerja Pegawai di atas Ekspektasi.",
                ]
            ],
        )

    def test_csv_writer_quotes_text_and_preserves_embedded_newlines(self) -> None:
        output = StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_NONNUMERIC, lineterminator="\n")
        writer.writerows(
            _normalized_table(
                [
                    ["No.", "Predikat Kinerja\nPegawai", "Penjelasan"],
                    ["1", "Sangat baik", "Baris pertama\nBaris kedua"],
                    ["2", "Baik", "1. Satu\n2. Dua"],
                ]
            )
        )

        self.assertEqual(
            output.getvalue(),
            '"No.","Predikat Kinerja Pegawai","Penjelasan"\n'
            '1,"Sangat baik","Baris pertama Baris kedua"\n'
            '2,"Baik","1. Satu \n2. Dua"\n',
        )

    def test_usable_tables_drops_one_column_fragments_when_full_table_exists(self) -> None:
        full_table = [["No", "Kategori"], ["2", "Tenaga Ahli"], ["3", "Perwakilan Negara"]]
        fragments = [[["Ahli"], ["Madya"]], [["Jumlah"], ["kegiatan"]]]

        self.assertEqual(_usable_tables([full_table, *fragments]), [full_table])

    def test_postprocess_compacts_jenjang_table(self) -> None:
        table = _normalized_table(
            [
                [
                    "No",
                    "Kategori",
                    "Hasil Kerja",
                    "Indikator",
                    "Target",
                    "Satuan",
                    "Penjelasan",
                    "",
                    "",
                    "Bukti Kelengkapan",
                    "",
                    "",
                    "",
                    "Jenjang Jabatan Sumber Daya Manusia",
                    "",
                    "",
                    "",
                    "",
                    "",
                ],
                ["", "", "", "", "", "", "", "", "", "", "", "", "", "Ilmu Pengetahuan dan Teknologi"],
                ["", "", "", "", "", "", "", "", "", "", "", "", "Ahli Utama", "", "Ahli Madya", "Ahli Muda", "Ahli Pertama"],
                [
                    "2",
                    "Tenaga Ahli",
                    "Menjadi tenaga\nahli dalam forum\nteknis nasional",
                    "Jumlah\nkegiatan",
                    "1",
                    "Kegiatan",
                    "",
                    "1. Peran aktif sebagai",
                    "",
                    "",
                    "1. Surat",
                    "",
                    "2,5",
                    "",
                    "2,5",
                    "2,5",
                    "2,5",
                ],
                ["", "", "", "", "", "", "", "tenaga ahli yang", "", "", "undangan/Surat"],
                ["", "", "", "", "", "", "", "diundang atau ditunjuk", "", "", "tugas/Letter of"],
                ["", "", "", "", "", "", "", "2. Berlaku kelipatan per-", "", "", "2. Laporan kegiatan"],
                ["", "", "", "", "", "", "", "program/kegiatan"],
            ]
        )

        self.assertEqual(
            _postprocess_table(table),
            [
                [
                    "No",
                    "Kategori",
                    "Hasil Kerja",
                    "Indikator",
                    "Target",
                    "Satuan",
                    "Penjelasan",
                    "Bukti Kelengkapan",
                    "Ahli Utama",
                    "Ahli Madya",
                    "Ahli Muda",
                    "Ahli Pertama",
                ],
                [
                    2,
                    "Tenaga Ahli",
                    "Menjadi tenaga ahli dalam forum teknis nasional",
                    "Jumlah kegiatan",
                    1,
                    "Kegiatan",
                    "1. Peran aktif sebagai tenaga ahli yang diundang atau ditunjuk \n"
                    "2. Berlaku kelipatan per- program/kegiatan",
                    "1. Surat undangan/Surat tugas/Letter of \n2. Laporan kegiatan",
                    "2,5",
                    "2,5",
                    "2,5",
                    "2,5",
                ],
            ],
        )


if __name__ == "__main__":
    unittest.main()
