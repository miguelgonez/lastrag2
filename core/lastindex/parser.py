"""
LastRAG v2 — LastIndex: Parser Estructural
==========================================
Convierte un documento (PDF/DOCX) en un arbol jerarquico de bloques con
pagina y ruta de seccion. Docling es el parser primario; si no esta
disponible, hay un fallback con PyMuPDF basado en heuristicas de encabezado.

Salida: lista de `ParsedBlock` lista para ingestar en Neo4j (ingest.py).
El `block_id` se genera de forma DETERMINISTA (hash de document_id+page+order)
para que la reindexacion sea idempotente y el backend vectorial pueda usar
exactamente el mismo id como locator.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ParsedBlock:
    block_id: str
    text: str
    page: int
    section_path: str
    section_title: str
    chapter: Optional[str]
    order: int


@dataclass
class ParsedDocument:
    document_id: str
    title: str
    source_path: str
    blocks: list[ParsedBlock] = field(default_factory=list)
    specialty: Optional[str] = None
    doc_type: Optional[str] = None


def make_block_id(document_id: str, page: int, order: int) -> str:
    """ID determinista: misma entrada -> mismo id (reindex idempotente)."""
    raw = f"{document_id}:{page}:{order}".encode("utf-8")
    return "blk_" + hashlib.sha1(raw).hexdigest()[:16]


def make_document_id(source_path: str) -> str:
    name = Path(source_path).stem
    digest = hashlib.sha1(source_path.encode("utf-8")).hexdigest()[:8]
    return f"doc_{name}_{digest}"


class StructuralParser:
    """
    Parser primario via Docling. Detecta titulos, secciones y paginas y
    construye la ruta de seccion ("Cap 3 > 3.2 Dosificacion").
    """

    def __init__(self, min_block_chars: int = 40):
        self.min_block_chars = min_block_chars

    def parse(
        self,
        file_path: str,
        *,
        specialty: Optional[str] = None,
        doc_type: Optional[str] = None,
    ) -> ParsedDocument:
        document_id = make_document_id(file_path)
        title = Path(file_path).stem

        blocks = self._parse_with_docling(file_path, document_id)
        if blocks is None:
            blocks = self._parse_with_pymupdf(file_path, document_id)

        return ParsedDocument(
            document_id=document_id,
            title=title,
            source_path=file_path,
            blocks=blocks,
            specialty=specialty,
            doc_type=doc_type,
        )

    # --- Parser primario: Docling ---
    def _parse_with_docling(
        self, file_path: str, document_id: str
    ) -> Optional[list[ParsedBlock]]:
        try:
            from docling.document_converter import DocumentConverter
        except ImportError:
            print("⚠️ Docling no instalado → fallback PyMuPDF")
            return None

        try:
            converter = DocumentConverter()
            result = converter.convert(file_path)
            doc = result.document

            blocks: list[ParsedBlock] = []
            order = 0
            current_chapter: Optional[str] = None
            section_stack: list[str] = []

            # Recorremos los items del documento Docling en orden de lectura.
            for item, _level in doc.iterate_items():
                label = getattr(item, "label", "") or ""
                text = (getattr(item, "text", "") or "").strip()
                page = self._page_of(item)

                if not text:
                    continue

                lname = str(label).lower()
                if "title" in lname or "chapter" in lname:
                    current_chapter = text
                    section_stack = []
                    continue
                if "section_header" in lname or "heading" in lname:
                    # Profundidad aproximada por nivel del header
                    section_stack = [text]
                    continue

                if len(text) < self.min_block_chars:
                    continue

                section_path = self._build_path(current_chapter, section_stack)
                section_title = section_stack[-1] if section_stack else (
                    current_chapter or "Cuerpo"
                )
                blocks.append(
                    ParsedBlock(
                        block_id=make_block_id(document_id, page, order),
                        text=text,
                        page=page,
                        section_path=section_path,
                        section_title=section_title,
                        chapter=current_chapter,
                        order=order,
                    )
                )
                order += 1

            print(f"✅ Docling: {len(blocks)} bloques estructurales")
            return blocks
        except Exception as e:  # pragma: no cover
            print(f"⚠️ Docling fallo ({e}) → fallback PyMuPDF")
            return None

    # --- Fallback: PyMuPDF con heuristicas ---
    def _parse_with_pymupdf(
        self, file_path: str, document_id: str
    ) -> list[ParsedBlock]:
        import fitz  # pymupdf

        blocks: list[ParsedBlock] = []
        order = 0
        current_section = "Cuerpo"

        with fitz.open(file_path) as pdf:
            # Tamano de fuente mediano para distinguir encabezados de cuerpo
            for page_index in range(pdf.page_count):
                page = pdf[page_index]
                page_no = page_index + 1
                data = page.get_text("dict")
                body_sizes: list[float] = []
                for blk in data.get("blocks", []):
                    for line in blk.get("lines", []):
                        for span in line.get("spans", []):
                            body_sizes.append(span.get("size", 0))
                median = sorted(body_sizes)[len(body_sizes) // 2] if body_sizes else 0

                for blk in data.get("blocks", []):
                    text_parts: list[str] = []
                    max_size = 0.0
                    for line in blk.get("lines", []):
                        for span in line.get("spans", []):
                            text_parts.append(span.get("text", ""))
                            max_size = max(max_size, span.get("size", 0))
                    text = " ".join(text_parts).strip()
                    if not text:
                        continue

                    # Heuristica: fuente notablemente mayor que la mediana = encabezado
                    if max_size > median * 1.25 and len(text) < 120:
                        current_section = text
                        continue

                    if len(text) < self.min_block_chars:
                        continue

                    blocks.append(
                        ParsedBlock(
                            block_id=make_block_id(document_id, page_no, order),
                            text=text,
                            page=page_no,
                            section_path=current_section,
                            section_title=current_section,
                            chapter=None,
                            order=order,
                        )
                    )
                    order += 1

        print(f"✅ PyMuPDF (fallback): {len(blocks)} bloques")
        return blocks

    # --- utilidades ---
    @staticmethod
    def _page_of(item) -> int:
        prov = getattr(item, "prov", None)
        if prov:
            try:
                return int(prov[0].page_no)
            except Exception:
                pass
        return 1

    @staticmethod
    def _build_path(chapter: Optional[str], stack: list[str]) -> str:
        parts = [p for p in ([chapter] if chapter else []) + stack if p]
        return " > ".join(parts) if parts else "Cuerpo"
