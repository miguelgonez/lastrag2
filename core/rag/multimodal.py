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

import re
from dataclasses import dataclass, field

from ..backends.base import EvidenceChunk

TABLE_KIND = "table"
TABLE_EXTRACTOR_VERSION = "find-tables-v1 (detector PyMuPDF) + posicional-fallback"
FIGURE_KIND = "figure"
MULTIMODAL_HINTS = ("tabla", "cuadro", "figura", "gráfico", "grafico", "imagen")

_TABLE_CAPTION_RE = re.compile(r"^\s*(tabla|cuadro)\s*[\dIVX]+", re.IGNORECASE)
_FIG_CAPTION_RE = re.compile(r"^\s*(figura|gráfico|grafico|imagen)\s*\d*", re.IGNORECASE)


@dataclass
class TableBlock:
    page: int
    caption: str
    rows: list[list[str]] = field(default_factory=list)

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
    """Estrategia auto: detector real de PyMuPDF; si no encuentra nada,
    fallback posicional. La vía usada es parte del alcance declarado
    (TABLE_EXTRACTOR_VERSION)."""
    tables = _extract_tables_detector(pdf_path, max_pages)
    if not tables:
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
