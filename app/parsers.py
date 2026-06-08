from __future__ import annotations

import re
from pathlib import Path

import fitz
from bs4 import BeautifulSoup
from docx import Document as DocxDocument

from .models import ParsedBlock
from .utils import normalize_whitespace


SUPPORTED_SUFFIXES = {".pdf", ".docx", ".md", ".markdown", ".html", ".htm", ".txt"}


def detect_source_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported file type: {suffix}")
    return suffix.lstrip(".")


def parse_file(path: Path) -> tuple[str, str, list[ParsedBlock]]:
    source_type = detect_source_type(path)
    if source_type == "pdf":
        title, blocks = _parse_pdf(path)
    elif source_type == "docx":
        title, blocks = _parse_docx(path)
    elif source_type in {"md", "markdown"}:
        title, blocks = _parse_markdown(path)
    elif source_type in {"html", "htm"}:
        title, blocks = _parse_html(path)
    else:
        title, blocks = _parse_text(path)
    return title, source_type, blocks


def _parse_markdown(path: Path) -> tuple[str, list[ParsedBlock]]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    title = path.stem
    heading_stack: list[str] = []
    blocks: list[ParsedBlock] = []
    current_lines: list[str] = []
    current_title = title

    def flush() -> None:
        nonlocal current_lines, current_title
        content = normalize_whitespace("\n".join(current_lines))
        if content:
            blocks.append(
                ParsedBlock(
                    title=current_title,
                    content=content,
                    section_path=heading_stack.copy(),
                )
            )
        current_lines = []

    for line in raw.splitlines():
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match:
            flush()
            level = len(match.group(1))
            heading = normalize_whitespace(match.group(2))
            if not heading:
                continue
            if level == 1 and title == path.stem:
                title = heading
            while len(heading_stack) >= level:
                heading_stack.pop()
            heading_stack.append(heading)
            current_title = heading
        else:
            current_lines.append(line)
    flush()
    if not blocks:
        blocks.append(ParsedBlock(title=title, content=normalize_whitespace(raw), section_path=[title]))
    return title, blocks


def _parse_text(path: Path) -> tuple[str, list[ParsedBlock]]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    title = path.stem
    paragraphs = [normalize_whitespace(part) for part in re.split(r"\n\s*\n", raw) if part.strip()]
    blocks = [ParsedBlock(title=title, content=part, section_path=[title]) for part in paragraphs]
    return title, blocks or [ParsedBlock(title=title, content=normalize_whitespace(raw), section_path=[title])]


def _parse_html(path: Path) -> tuple[str, list[ParsedBlock]]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(raw, "html.parser")
    title = normalize_whitespace((soup.title.string if soup.title and soup.title.string else path.stem))
    blocks: list[ParsedBlock] = []
    heading_stack: list[str] = []
    current_lines: list[str] = []
    current_title = title

    def flush() -> None:
        nonlocal current_lines, current_title
        content = normalize_whitespace("\n".join(current_lines))
        if content:
            blocks.append(
                ParsedBlock(
                    title=current_title,
                    content=content,
                    section_path=heading_stack.copy() or [title],
                )
            )
        current_lines = []

    for element in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "code"]):
        if element.name and element.name.startswith("h"):
            flush()
            level = int(element.name[1])
            heading = normalize_whitespace(element.get_text(" ", strip=True))
            if not heading:
                continue
            while len(heading_stack) >= level:
                heading_stack.pop()
            heading_stack.append(heading)
            current_title = heading
            if level == 1:
                title = heading
        else:
            text = normalize_whitespace(element.get_text(" ", strip=True))
            if text:
                current_lines.append(text)
    flush()
    return title, blocks or [ParsedBlock(title=title, content=normalize_whitespace(soup.get_text("\n")), section_path=[title])]


def _parse_docx(path: Path) -> tuple[str, list[ParsedBlock]]:
    document = DocxDocument(path)
    title = path.stem
    heading_stack: list[str] = []
    blocks: list[ParsedBlock] = []
    current_lines: list[str] = []
    current_title = title

    def flush() -> None:
        nonlocal current_lines, current_title
        content = normalize_whitespace("\n".join(current_lines))
        if content:
            blocks.append(
                ParsedBlock(
                    title=current_title,
                    content=content,
                    section_path=heading_stack.copy() or [title],
                )
            )
        current_lines = []

    for paragraph in document.paragraphs:
        text = normalize_whitespace(paragraph.text)
        if not text:
            continue
        style_name = paragraph.style.name.lower() if paragraph.style and paragraph.style.name else ""
        if style_name.startswith("heading"):
            flush()
            match = re.search(r"(\d+)", style_name)
            level = int(match.group(1)) if match else 1
            while len(heading_stack) >= level:
                heading_stack.pop()
            heading_stack.append(text)
            current_title = text
            if level == 1:
                title = text
        else:
            current_lines.append(text)
    flush()
    return title, blocks or [ParsedBlock(title=title, content=title, section_path=[title])]


def _parse_pdf(path: Path) -> tuple[str, list[ParsedBlock]]:
    doc = fitz.open(path)
    title = path.stem
    blocks: list[ParsedBlock] = []
    for page_index, page in enumerate(doc, start=1):
        page_blocks = page.get_text("blocks")
        texts = [normalize_whitespace(item[4]) for item in page_blocks if len(item) >= 5 and item[4].strip()]
        merged = [text for text in texts if text]
        for part in merged:
            blocks.append(
                ParsedBlock(
                    title=title,
                    content=part,
                    page=page_index,
                    section_path=[f"Page {page_index}"],
                    metadata={"page": page_index},
                )
            )
    doc.close()
    return title, blocks or [ParsedBlock(title=title, content=title, section_path=[title])]

