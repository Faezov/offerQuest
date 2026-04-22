from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from offerquest.extractors import (
    clean_legacy_word_lines,
    extract_docx_text,
    extract_odt_like_text,
)


class ExtractorTests(unittest.TestCase):
    def test_extract_odt_like_text_reads_content_xml(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:body>
    <office:text>
      <text:p>Hello world</text:p>
      <text:p>Second paragraph</text:p>
    </office:text>
  </office:body>
</office:document-content>
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.doc"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("content.xml", xml)

            extracted = extract_odt_like_text(path)

        self.assertEqual(extracted, "Hello world\nSecond paragraph")

    def test_clean_legacy_word_lines_filters_style_noise(self) -> None:
        lines = [
            "Root Entry",
            "Heading 1",
            "Bulat Faezov, M.Sc.",
            "Professional Summary",
            "SQL querying",
            "WordDocument",
        ]

        self.assertEqual(
            clean_legacy_word_lines(lines),
            [
                "Bulat Faezov, M.Sc.",
                "Professional Summary",
                "SQL querying",
            ],
        )

    def test_extract_docx_text_reads_word_document_xml(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:r><w:t>Hello</w:t></w:r>
      <w:r><w:tab/></w:r>
      <w:r><w:t>world</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>Second paragraph</w:t></w:r>
    </w:p>
  </w:body>
</w:document>
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", xml)

            extracted = extract_docx_text(path)

        self.assertEqual(extracted, "Hello world\nSecond paragraph")


if __name__ == "__main__":
    unittest.main()
