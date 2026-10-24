"""C-G3 (NH-EG-LOOP-001): el source_meta curado CASA con la evidencia de
Wave 1 y la capa 5 decide con él — permitido y bloqueado por código.

Cobertura exigida por el paquete:
  - permitido: chunk con document_id 'pubmed_<pmid>' y store curado ⇒
    qualified; engine.run con dobles ⇒ affirmable=true.
  - bloqueado: PMID retractado REAL del corpus (84 en el barrido del 23-oct;
    aquí 33245682, marcado 'retracted' fuente pubmed) ⇒ RETRACTED, bloqueante.
  - bloqueado: PMID ausente del store ⇒ UNKNOWN_TIER, no afirma.
  - las tres formas de clave resuelven al MISMO registro.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.backends.base import Citation, EvidenceChunk
from core.rag.provenance import (PEER_REVIEWED, RETRACTED, UNKNOWN_TIER,
                                 assess, lookup, qualify)
from core.rag.source_meta_store import SourceMetaStore

# PMID retractado REAL del corpus (barrido 23-oct: retracted, fuente pubmed)
RETRACTED_PMID = "33245682"
OK_PMID = "29605144"
TODAY = date.today().isoformat()

CURACION = {
    OK_PMID: {"tier": PEER_REVIEWED, "retraction_status": "none",
              "retraction_checked_at": TODAY, "retraction_source": "pubmed+rwdb",
              "identifier": OK_PMID},
    RETRACTED_PMID: {"tier": PEER_REVIEWED, "retraction_status": "retracted",
                     "retraction_checked_at": TODAY,
                     "retraction_source": "pubmed",
                     "identifier": RETRACTED_PMID},
}


def _store() -> SourceMetaStore:
    return SourceMetaStore(CURACION)


def _chunk(pmid: str) -> EvidenceChunk:
    """Chunk como llega en Wave 1: cita resuelta al TÍTULO, id estable aparte."""
    return EvidenceChunk(
        text=f"Abstract del documento {pmid}.",
        locator=f"pubmed_{pmid}::b1",
        citation=Citation(document=f"Título del artículo {pmid}",
                          document_id=f"pubmed_{pmid}",
                          section="Abstract", page=1, block_id=f"pubmed_{pmid}::b1"),
    )


# ── store ──────────────────────────────────────────────────────────────────

def test_store_carga_y_estampa(tmp_path):
    p = tmp_path / "source_meta_20261023.json"
    p.write_text(json.dumps(CURACION), encoding="utf-8")
    store = SourceMetaStore.from_curation(p)
    assert store.stamp["entries"] == 2
    assert len(store.stamp["sha256"]) == 64
    assert len(store) == 6          # 2 entradas × 3 formas de clave


def test_tres_formas_mismo_registro():
    store = _store()
    a = store[f"pubmed_{OK_PMID}"]
    b = store[f"pmid:{OK_PMID}"]
    c = store[OK_PMID]
    assert a is b is c


# ── capa 5 con el wiring ───────────────────────────────────────────────────

def test_permitido_document_id_casa_y_cualifica():
    q = lookup(_store(), _chunk(OK_PMID))
    assert q.tier == PEER_REVIEWED
    verdict = qualify(q)
    assert verdict.qualified and verdict.reason.startswith("QUALIFIED")


def test_permitido_assess_affirmable_true():
    a = assess([_chunk(OK_PMID)], _store())
    assert a.affirmable is True


def test_bloqueado_pmid_retractado_real():
    verdict = qualify(lookup(_store(), _chunk(RETRACTED_PMID)))
    assert verdict.qualified is False
    assert verdict.retraction_status == RETRACTED
    assert verdict.blocking is True          # contamina: la respuesta se retiene


def test_bloqueado_assess_con_retractado_no_affirmable():
    a = assess([_chunk(OK_PMID), _chunk(RETRACTED_PMID)], _store())
    assert a.affirmable is False
    assert a.blocking                                        # locus del retractado


def test_bloqueado_pmid_ausente_unknown_tier():
    q = lookup(_store(), _chunk("99999999"))
    assert q.tier == UNKNOWN_TIER
    assert qualify(q).qualified is False


# ── engine con dobles: affirmable real por primera vez ─────────────────────

def test_engine_run_affirmable_true_con_dobles():
    from core.rag.engine import LastRAGEngine
    from tests.doubles import FakeBackend, FakeLastIndex, FakeLLM

    # la respuesta del doble COINCIDE literalmente con el fragmento congelado:
    # sin eso el verificador (block por defecto) la retiraría — y con razón.
    respuesta = "La metformina es el tratamiento de primera linea (Guia DM2, p.42)."
    chunk = EvidenceChunk(
        text=respuesta,
        locator=f"pubmed_{OK_PMID}::b1",
        citation=Citation(document=f"Título del artículo {OK_PMID}",
                          document_id=f"pubmed_{OK_PMID}",
                          section="Abstract", page=1,
                          block_id=f"pubmed_{OK_PMID}::b1"),
    )
    backend = FakeBackend(corpus=[chunk])
    engine = LastRAGEngine(backend, FakeLastIndex(), FakeLLM(response=respuesta),
                           source_meta=_store(), source_policy="block")
    out = asyncio.run(engine.run("tratamiento de la diabetes tipo 2"))
    assert out["abstained"] is False
    assert out["affirmable"] is True


def test_engine_run_retractado_retiene():
    from core.rag.engine import LastRAGEngine
    from tests.doubles import FakeBackend, FakeLastIndex, FakeLLM

    chunk = EvidenceChunk(
        text="La metformina es el tratamiento de primera linea (Guia DM2, p.42).",
        locator=f"pubmed_{RETRACTED_PMID}::b1",
        citation=Citation(document=f"Título del artículo {RETRACTED_PMID}",
                          document_id=f"pubmed_{RETRACTED_PMID}",
                          section="Abstract", page=1,
                          block_id=f"pubmed_{RETRACTED_PMID}::b1"),
    )
    backend = FakeBackend(corpus=[chunk])
    engine = LastRAGEngine(backend, FakeLastIndex(), FakeLLM(),
                           source_meta=_store(), source_policy="block")
    out = asyncio.run(engine.run("tratamiento de la diabetes tipo 2"))
    assert out["affirmable"] is False
