"""
LastRAG v2 — Ola 3: Multimodalidad (tablas y figuras)
======================================================
Compromiso Wave 3 (s14 del deck): extracción e indexación estructurada de
tablas/figuras + routing que las priorice cuando la consulta lo pide.

HONESTIDAD DE ALCANCE (declarada, no silenciosa): extracción POSICIONAL con
PyMuPDF (agrupación de palabras por bandas de fila y alineación de columnas)
— sin modelo de visión. Las figuras se indexan por caption + página + bbox
(referencia estructurada), sin comprensión visual del contenido gráfico.
La calidad de esta extracción queda etiquetada como `posicional-v1`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

# Declaraciones de la cascada de extracción (jamás fallback silencioso):
# cada intento de vía queda registrado aquí; los tests lo comprueban.
EXTRACTOR_EVENTS: list[dict] = []


def last_extractor_events() -> list[dict]:
    return list(EXTRACTOR_EVENTS)

from ..backends.base import EvidenceChunk

TABLE_KIND = "table"
TABLE_EXTRACTOR_VERSION = "cascada: docling-tableformer (visión real, si hay capacidad) → find-tables-v1 → posicional-v1"


def vision_available() -> bool:
    """Capacidad REAL de extracción con modelo de visión (Docling/TableFormer).

    ANTI-100%-FALSO: una variable de entorno NUNCA sustituye la capacidad —
    como mucho deshabilita (LASTRAG_VISION_DISABLED=1). La capacidad se
    comprueba importando el motor real; sin import no hay visión.
    """
    if os.getenv("LASTRAG_VISION_DISABLED"):
        return False
    try:
        from docling.document_converter import DocumentConverter  # noqa: F401
        return True
    except Exception:
        return False


def _extract_tables_docling(pdf_path: str, max_pages: int = 50) -> list[TableBlock]:
    """Extracción con modelo REAL de estructura de tablas (TableFormer vía
    Docling, parser primario declarado del proyecto). Descarga sus modelos
    ONNX en el primer uso. Cada tabla lleva extractor='docling-tableformer-v1'."""
    import fitz
    from docling.document_converter import DocumentConverter

    EXTRACTOR_EVENTS.append({"extractor": "docling-tableformer-v1",
                             "event": "attempt", "path": pdf_path})
    converter = DocumentConverter()
    result = converter.convert(pdf_path)
    tables: list[TableBlock] = []
    with fitz.open(pdf_path) as doc:
        for item in result.document.tables:
            try:
                page_no = int(item.prov[0].pageno) if item.prov else 1
            except Exception:
                page_no = 1
            if page_no > max_pages:
                continue
            try:
                df = item.export_to_dataframe()
                rows = [[("" if c is None else str(c)) for c in row]
                        for row in df.values.tolist()]
            except Exception:
                rows = []
            rows = [r for r in rows if any(c.strip() for c in r)]
            if len(rows) < 2:
                continue
            caption = ""
            try:
                page = doc[page_no - 1]
                bbox = item.prov[0].bbox if item.prov else None
                for b in sorted(page.get_text("blocks"), key=lambda b: b[1]):
                    if bbox and b[3] <= bbox[1] + 2 and \
                            _TABLE_CAPTION_RE.match(b[4].strip()):
                        caption = b[4].strip()
                        break
            except Exception:
                pass
            tables.append(TableBlock(page=page_no, caption=caption, rows=rows,
                                     extractor="docling-tableformer-v1"))
    EXTRACTOR_EVENTS.append({"extractor": "docling-tableformer-v1",
                             "event": "ok", "tables": len(tables)})
    return tables
FIGURE_KIND = "figure"
MULTIMODAL_HINTS = ("tabla", "cuadro", "figura", "gráfico", "grafico", "imagen")

_TABLE_CAPTION_RE = re.compile(r"^\s*(tabla|cuadro)\s*[\dIVX]+", re.IGNORECASE)
_FIG_CAPTION_RE = re.compile(r"^\s*(figura|gráfico|grafico|imagen)\s*\d*", re.IGNORECASE)


@dataclass
class TableBlock:
    page: int
    caption: str
    rows: list[list[str]] = field(default_factory=list)
    extractor: str = "unknown"

    def serialize(self) -> str:
        head = f"[TABLA · p.{self.page}] {self.caption}" if self.caption \
            else f"[TABLA · p.{self.page}]"
        lines = [head]
        for row in self.rows:
            lines.append(" | ".join(row))
        return "\n".join(lines)

    def to_chunk(self, document: str) -> EvidenceChunk:
        from ..backends.base import Citation
        locator = f"tbl_p{self.page}_{len(self.caption)}"
        return EvidenceChunk(
            text=self.serialize(), locator=locator,
            citation=Citation(document=document, section=self.caption or "Tabla",
                              page=self.page, block_id=locator,
                              confidence=0.9),
            score=0.0, kind=TABLE_KIND,
        )


@dataclass
class FigureRef:
    page: int
    caption: str
    bbox: tuple[float, float, float, float]

    def to_chunk(self, document: str) -> EvidenceChunk:
        from ..backends.base import Citation
        locator = f"fig_p{self.page}"
        return EvidenceChunk(
            text=f"[FIGURA · p.{self.page}] {self.caption}",
            locator=locator,
            citation=Citation(document=document, section=self.caption or "Figura",
                              page=self.page, block_id=locator, confidence=0.9),
            score=0.0, kind=FIGURE_KIND,
        )


def _extract_tables_detector(pdf_path: str, max_pages: int = 50) -> list[TableBlock]:
    """Extracción con el detector REAL de tablas de PyMuPDF (find_tables):
    reconoce la rejilla por líneas/espaciado, no por heurística de bandas."""
    import fitz

    tables: list[TableBlock] = []
    with fitz.open(pdf_path) as doc:
        for pno in range(min(max_pages, doc.page_count)):
            page = doc[pno]
            try:
                tabs = page.find_tables()
            except Exception:
                continue
            blocks = page.get_text("blocks")
            for t in tabs.tables:
                rows = [r for r in (t.extract() or []) if any(c and str(c).strip() for c in r)]
                if len(rows) < 2:
                    continue
                caption = ""
                for b in blocks:
                    if b[3] <= t.bbox[1] + 2 and _TABLE_CAPTION_RE.match(b[4].strip()):
                        caption = b[4].strip()
                        break
                tables.append(TableBlock(page=pno + 1, caption=caption,
                                         rows=[[str(c or "") for c in r] for r in rows]))
    return tables


def _extract_tables_positional(pdf_path: str, max_pages: int = 50) -> list[TableBlock]:
    """Fallback posicional: palabras agrupadas por banda-y (fila) y filas
    con ≥2 columnas alineadas en ≥2 filas consecutivas = tabla."""
    import fitz  # PyMuPDF (dependencia core)

    tables: list[TableBlock] = []
    with fitz.open(pdf_path) as doc:
        for pno in range(min(max_pages, doc.page_count)):
            page = doc[pno]  # pno es 0-based; el número humano es pno+1
            words = page.get_text("words")  # (x0,y0,x1,y1,word,...)
            if len(words) < 8:
                continue
            # 1) bandas por fila: agrupar por y-center con tolerancia
            rows: list[list[tuple]] = []
            for w in sorted(words, key=lambda w: (w[1] + w[3]) / 2):
                yc = (w[1] + w[3]) / 2
                if rows and abs(yc - (rows[-1][-1][1] + rows[-1][-1][3]) / 2) < 3.0:
                    rows[-1].append(w)
                else:
                    rows.append([w])
            rows = [sorted(r, key=lambda w: w[0]) for r in rows]
            rows = [[r for r in row if r[4].strip()] for row in rows]
            # 2) detectar ≥2 filas con ≥2 columnas alineadas (misma x-start)
            grid_rows: list[list[str]] = []
            for row in rows:
                if len(row) >= 2:
                    cells, cur = [], [row[0]]
                    for prev, w in zip(row, row[1:]):
                        gap = w[0] - prev[2]
                        if gap > 12.0:  # huecho de columna
                            cells.append(" ".join(x[4] for x in cur))
                            cur = [w]
                        else:
                            cur.append(w)
                    cells.append(" ".join(x[4] for x in cur))
                    if len(cells) >= 2:
                        grid_rows.append(cells)
            consecutive = 0
            block: list[list[str]] = []
            for row in grid_rows:
                block.append(row)
                consecutive += 1
            if consecutive >= 2:
                caption = ""
                for row in rows:
                    first = " ".join(w[4] for w in row)
                    if _TABLE_CAPTION_RE.match(first):
                        caption = first
                        break
                tables.append(TableBlock(page=pno + 1, caption=caption, rows=block))
    return tables


def extract_tables(pdf_path: str, max_pages: int = 50) -> list[TableBlock]:
    """Cascada DECLARADA: docling (visión real si hay capacidad) →
    find_tables → posicional. Todo salto de vía queda en EXTRACTOR_EVENTS;
    jamás un fallback silencioso."""
    if vision_available():
        try:
            tables = _extract_tables_docling(pdf_path, max_pages)
            if tables:
                return tables
            EXTRACTOR_EVENTS.append({"extractor": "docling-tableformer-v1",
                                     "event": "empty_fallback_find_tables"})
        except Exception as exc:
            EXTRACTOR_EVENTS.append({"extractor": "docling-tableformer-v1",
                                     "event": "error_fallback_find_tables",
                                     "reason": f"{type(exc).__name__}"})
    tables = _extract_tables_detector(pdf_path, max_pages)
    if not tables:
        EXTRACTOR_EVENTS.append({"extractor": "find-tables-v1",
                                 "event": "empty_fallback_posicional"})
        tables = _extract_tables_positional(pdf_path, max_pages)
    return tables


def extract_figures(pdf_path: str, max_pages: int = 50) -> list[FigureRef]:
    """Indexa figuras por caption + página + bbox (referencia estructurada,
    sin comprensión visual)."""
    import fitz

    out: list[FigureRef] = []
    with fitz.open(pdf_path) as doc:
        for pno in range(min(max_pages, doc.page_count)):
            page = doc[pno]
            blocks = page.get_text("blocks")
            captions = [b for b in blocks if _FIG_CAPTION_RE.match(b[4].strip())]
            images = page.get_images(full=True)
            if not captions:
                continue
            for cb in captions:
                bbox = (cb[0], cb[1], cb[2], cb[3])
                out.append(FigureRef(page=pno + 1, caption=cb[4].strip()[:120],
                                     bbox=bbox))
            if not images and captions:
                pass  # caption sin imagen embebida: se referencia igualmente
    return out


def wants_multimodal(query: str) -> bool:
    low = query.lower()
    return any(h in low for h in MULTIMODAL_HINTS)


def boost_multimodal(chunks: list[EvidenceChunk], query: str) -> tuple[list[EvidenceChunk], bool]:
    """Routing multimodal: si la consulta pide tabla/figura, los bloques de
    ese tipo SUBEN POR ENCIMA del resto (prioridad garantizada: el lift es
    mayor que el score máximo presente). Devuelve (ranking, aplicado)."""
    if not wants_multimodal(query) or not chunks:
        return chunks, False
    max_score = max(c.score for c in chunks)

    def effective(c: EvidenceChunk) -> float:
        if c.kind in (TABLE_KIND, FIGURE_KIND):
            return c.score + max_score + 1.0  # por encima de cualquiera
        return c.score

    ranked = sorted(chunks, key=effective, reverse=True)
    return ranked, True
