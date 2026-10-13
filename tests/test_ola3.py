"""Ola 3 — CB-15: multimodalidad. Extracción posicional de tablas (PyMuPDF),
referencias de figuras por caption y routing multimodal.
ALCANCE DECLARADO: sin modelo de visión — extracción posicional etiquetada
(posicional-v1); la comprensión visual NO se reclama."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fitz

from core.backends.base import EvidenceChunk
from core.rag.engine import LastRAGEngine
from core.rag.multimodal import (
    extract_tables, extract_figures, boost_multimodal,
    TABLE_KIND, FIGURE_KIND,
)
from tests.doubles import FakeBackend, FakeLastIndex, FakeLLM


def _make_pdf(tmp_path) -> str:
    """PDF sintético con una tabla real (palabras alineadas en columnas),
    caption de tabla y caption de figura."""
    path = tmp_path / "guia_tablas.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), "Guía clínica de demostración",
                     fontsize=14)
    # caption de tabla
    page.insert_text((72, 90), "Tabla 1: Dosis de metformina por función renal",
                     fontsize=11)
    # tabla: 3 filas × 3 columnas alineadas
    rows = [("Estadio", "Dosis inicial", "Máximo"),
            ("Normal", "500 mg", "2550 mg"),
            ("Leve", "500 mg", "2000 mg"),
            ("Moderada", "250 mg", "1000 mg")]
    y = 120
    for row in rows:
        for col, cell in enumerate(row):
            page.insert_text((80 + col * 130, y), cell, fontsize=10)
        y += 20
    # caption de figura (sin imagen embebida: se referencia igualmente)
    page.insert_text((72, y + 20), "Figura 1: Curva dosis-respuesta",
                     fontsize=11)
    doc.save(str(path))
    doc.close()
    return str(path)


def test_cb15_extract_table_permitted(tmp_path):
    tables = extract_tables(_make_pdf(tmp_path))
    assert tables, "no extrajo ninguna tabla"
    tbl = tables[0]
    assert tbl.caption and "Tabla 1" in tbl.caption
    flat = " ".join(" ".join(r) for r in tbl.rows)
    assert "2550" in flat and "Moderada" in flat
    assert tbl.page == 1


def test_cb15_table_chunk_is_typed_and_cited_permitted(tmp_path):
    tables = extract_tables(_make_pdf(tmp_path))
    chunk = tables[0].to_chunk("Guía demo")
    assert chunk.kind == TABLE_KIND
    assert chunk.citation.page == 1
    assert "[TABLA" in chunk.text  # etiqueta honesta en la serialización


def test_cb15_extract_figures_permitted(tmp_path):
    figs = extract_figures(_make_pdf(tmp_path))
    assert figs and any("Figura 1" in f.caption for f in figs)
    chunk = figs[0].to_chunk("Guía demo")
    assert chunk.kind == FIGURE_KIND


def test_cb15_routing_boosts_table_when_asked_permitted():
    text_chunk = EvidenceChunk(text="La metformina es primera línea en DM2.",
                               locator="blk_text", score=5.0)
    table_chunk = EvidenceChunk(text="[TABLA · p.1] Dosis por función renal",
                                locator="tbl_1", score=0.5, kind=TABLE_KIND)
    ranked, applied = boost_multimodal([text_chunk, table_chunk],
                                       "muéstrame la tabla de dosis")
    assert applied is True
    assert ranked[0].locator == "tbl_1"


def test_cb15_no_multimodal_hint_no_reorder_blocked():
    text_chunk = EvidenceChunk(text="La metformina es primera línea.",
                               locator="blk_text", score=5.0)
    table_chunk = EvidenceChunk(text="[TABLA · p.1] Dosis", locator="tbl_1",
                                score=0.5, kind=TABLE_KIND)
    ranked, applied = boost_multimodal([text_chunk, table_chunk],
                                       "¿qué es la metformina?")
    assert applied is False
    assert ranked[0].locator == "blk_text"  # sin pista, el orden no se toca


def test_cb15_engine_multimodal_declared_permitted():
    """Engine end-to-end: la ruta structural con hint de tabla activa el boost
    y queda declarado en features."""
    class TableLastIndex(FakeLastIndex):
        async def structural_search(self, query, *, top_k=5):
            from core.backends.base import Citation
            return [
                EvidenceChunk(text="[TABLA · p.1] Dosis por función renal",
                              locator="tbl_1", score=2.0, kind=TABLE_KIND,
                              citation=Citation(document="Guía",
                                                section="Tabla 1", page=1,
                                                block_id="tbl_1")),
                EvidenceChunk(text="Dosis inicial: 500 mg/día.",
                              locator="blk_dose", score=1.5),
            ]
    engine = LastRAGEngine(FakeBackend(), TableLastIndex(), FakeLLM())
    result = asyncio.run(engine.run(
        "¿dónde está la tabla de dosis?"))  # hint exacto → ruta structural
    assert result["features"]["multimodal_boost"] is True
    assert result["evidence"][0]["kind"] == TABLE_KIND
