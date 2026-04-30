from __future__ import annotations

import csv
from io import StringIO
import unittest

from lembar.extraction import _normalized_table


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


if __name__ == "__main__":
    unittest.main()
