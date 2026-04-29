from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from offerquest.docx import clean_export_lines, export_document_as_docx
from offerquest.extractors import read_document_text


class DocxTests(unittest.TestCase):
    def test_clean_export_lines_removes_known_noise(self) -> None:
        lines = [
            "Lee, Jordan",
            "Jordan Lee, M.Sc.",
            "Professional Summary",
            "Normal.dotm",
            "Jordan Lee Curriculum vitae",
            "Template42",
        ]

        self.assertEqual(
            clean_export_lines(lines),
            [
                "Jordan Lee, M.Sc.",
                "Professional Summary",
            ],
        )

    def test_export_document_as_docx_creates_readable_docx(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "resume.txt"
            output_path = Path(tmpdir) / "resume.docx"
            input_path.write_text(
                "Jordan Lee\nProfessional Summary\nSQL and Python\n",
                encoding="utf-8",
            )

            export_document_as_docx(input_path, output_path)

            extracted = read_document_text(output_path)

        self.assertIn("Jordan Lee", extracted)
        self.assertIn("Professional Summary", extracted)
        self.assertIn("SQL and Python", extracted)


if __name__ == "__main__":
    unittest.main()
