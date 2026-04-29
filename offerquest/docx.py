from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from .extractors import read_document_text

DOCX_CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

DOCX_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""

DOCX_DOCUMENT_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
{paragraphs}
    <w:sectPr>
      <w:pgSz w:w="12240" w:h="15840"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>
"""

EXPORT_NOISE_LINES = {
    "Normal.dotm",
}


def export_document_as_docx(input_path: str | Path, output_path: str | Path) -> None:
    text = read_document_text(input_path)
    lines = clean_export_lines(text.splitlines())
    write_simple_docx(output_path, lines)


def clean_export_lines(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    previous = ""

    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        if line in EXPORT_NOISE_LINES:
            continue
        if line.lower().endswith("curriculum vitae"):
            continue
        if looks_like_binary_noise(line):
            continue

        if index == 0 and index + 1 < len(lines):
            next_line = lines[index + 1].strip()
            if is_name_alias_line(line, next_line):
                continue

        if line == previous:
            continue

        cleaned.append(line)
        previous = line

    return cleaned


def looks_like_binary_noise(line: str) -> bool:
    if re.search(r"[`^\\]", line):
        return True
    if len(line) <= 12 and any(char.isdigit() for char in line) and " " not in line:
        return True
    return False


def is_name_alias_line(line: str, next_line: str) -> bool:
    if "," not in line:
        return False

    alias_parts = [part.strip().lower() for part in line.split(",", 1)]
    next_parts = re.sub(r",\s*[A-Z]\.[A-Z]\.[^.]*$", "", next_line).lower()
    return all(part in next_parts for part in alias_parts if part)


def write_simple_docx(output_path: str | Path, lines: list[str]) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    paragraphs = "\n".join(build_paragraph_xml(line) for line in lines)
    document_xml = DOCX_DOCUMENT_TEMPLATE.format(paragraphs=paragraphs)

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", DOCX_CONTENT_TYPES_XML)
        archive.writestr("_rels/.rels", DOCX_RELS_XML)
        archive.writestr("word/document.xml", document_xml)


def build_paragraph_xml(line: str) -> str:
    escaped = escape(line)
    return f'    <w:p><w:r><w:t xml:space="preserve">{escaped}</w:t></w:r></w:p>'
