from __future__ import annotations

import re
import subprocess
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

ZIP_MAGIC = b"PK\x03\x04"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

ODT_NAMESPACES = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}

DOCX_NAMESPACES = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}

LEGACY_WORD_NOISE = {
    "Root Entry",
    "CompObj",
    "1Table",
    "SummaryInformation",
    "WordDocument",
    "DocumentSummaryInformation",
    "Normal",
    "Default Paragraph Font",
    "Comment Reference",
    "Emphasis",
    "FollowedHyperlink",
    "Footnote Characters",
    "Hyperlink",
    "Strong",
    "Title Char",
    "Unresolved Mention",
    "Heading",
    "Body Text",
    "Caption",
    "Index",
    "Balloon Text",
    "Body Text 2",
    "Body Text 3",
    "Body Text Indent",
    "Comment Text",
    "Comment Subject",
    "Header and Footer",
    "Footer",
    "Footnote Text",
    "Header",
    "HTML Preformatted",
    "Normal (Web)",
    "Plain Text",
    "List Paragraph",
    "Times New Roman",
    "Arial",
    "Liberation Serif",
    "Courier New",
    "Calibri",
    "Wingdings",
    "Tahoma",
    "Baltica",
    "Symbol",
    "Microsoft Word-Dokument",
    "MSWordDoc",
    "Word.Document.8",
    "Heading 4 Char",
    "Noto Sans Devanagari",
    "Noto Sans CJK SC",
    "System Biology",
}


def read_document_text(path: str | Path) -> str:
    document_path = Path(path)
    header = document_path.read_bytes()[:8]

    if header.startswith(ZIP_MAGIC):
        return extract_zip_document_text(document_path)
    if header.startswith(OLE_MAGIC):
        return extract_legacy_word_text(document_path)

    return normalize_text(document_path.read_text(encoding="utf-8", errors="ignore"))


def extract_zip_document_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if "content.xml" in names:
            return extract_odt_like_text(path)
        if "word/document.xml" in names:
            return extract_docx_text(path)

    raise ValueError(f"{path} is a zip document, but its structure is not supported")


def extract_odt_like_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        if "content.xml" not in archive.namelist():
            raise ValueError(f"{path} does not contain content.xml")
        content = archive.read("content.xml")

    root = ET.fromstring(content)
    office_text = root.find(".//office:text", ODT_NAMESPACES)
    if office_text is None:
        raise ValueError(f"{path} does not contain office:text content")

    paragraph_tags = {
        f"{{{ODT_NAMESPACES['text']}}}p",
        f"{{{ODT_NAMESPACES['text']}}}h",
    }

    blocks: list[str] = []
    for node in office_text.iter():
        if node.tag not in paragraph_tags:
            continue
        text = normalize_inline_whitespace(flatten_xml_text(node))
        if text:
            blocks.append(text)

    return "\n".join(blocks)


def extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        if "word/document.xml" not in archive.namelist():
            raise ValueError(f"{path} does not contain word/document.xml")
        content = archive.read("word/document.xml")

    root = ET.fromstring(content)
    paragraph_tags = {
        f"{{{DOCX_NAMESPACES['w']}}}p",
    }

    blocks: list[str] = []
    for node in root.iter():
        if node.tag not in paragraph_tags:
            continue
        text = normalize_inline_whitespace(flatten_xml_text(node))
        if text:
            blocks.append(text)

    return "\n".join(blocks)


def extract_legacy_word_text(path: Path) -> str:
    outputs: list[str] = []

    for command in (
        ["strings", "-el", "-n", "5", str(path)],
        ["strings", "-n", "5", str(path)],
    ):
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "The `strings` command is required to extract legacy Word documents."
            ) from exc

        if result.stdout:
            outputs.extend(result.stdout.splitlines())

    cleaned = clean_legacy_word_lines(outputs)
    if not cleaned:
        raise ValueError(f"Could not extract readable text from {path}")

    return "\n".join(cleaned)


def clean_legacy_word_lines(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()

    for raw_line in lines:
        line = normalize_inline_whitespace(raw_line.replace("\x00", " ").strip())
        if len(line) < 2:
            continue
        if line in seen:
            continue
        if is_legacy_word_noise(line):
            continue
        if alpha_count(line) < 2:
            continue

        cleaned.append(line)
        seen.add(line)

    return cleaned


def is_legacy_word_noise(line: str) -> bool:
    if line in LEGACY_WORD_NOISE:
        return True
    if re.fullmatch(r"Heading \d", line):
        return True
    if re.fullmatch(r"WW8Num\d+(?:z\d+)?", line):
        return True
    if re.fullmatch(r"[!\"#$%&'()*+,./:;<=>?@\[\\\]^_`{|}~-]+", line):
        return True
    return False


def flatten_xml_text(element: ET.Element) -> str:
    parts: list[str] = []

    if element.text:
        parts.append(element.text)

    for child in element:
        local_name = child.tag.rsplit("}", 1)[-1]
        if local_name == "line-break":
            parts.append("\n")
        elif local_name in {"br", "cr"}:
            parts.append("\n")
        elif local_name == "tab":
            parts.append("\t")
        else:
            parts.append(flatten_xml_text(child))

        if child.tail:
            parts.append(child.tail)

    return "".join(parts)


def normalize_text(text: str) -> str:
    lines = [normalize_inline_whitespace(line) for line in text.splitlines()]
    non_empty = [line for line in lines if line]
    return "\n".join(non_empty)


def normalize_inline_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def alpha_count(text: str) -> int:
    return sum(char.isalpha() for char in text)
