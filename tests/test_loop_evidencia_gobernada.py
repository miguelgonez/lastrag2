"""El loop de evidencia gobernada es un control: aquí su caso permitido y sus
casos bloqueados. Un loop que acepte un 'pass' escrito a mano no gobierna nada."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location(
    "loop_eg", ROOT / "scripts" / "loop_evidencia_gobernada.py")
loop = importlib.util.module_from_spec(spec); spec.loader.exec_module(loop)
PLAN = json.loads((ROOT / "evidencia_gobernada" / "PLAN_GATES.json").read_text())
GATES = {g["id"]: g for g in PLAN["gates"]}


def _with_receipt(tmp_path, name: str, payload: dict):
    loop.RECEIPTS = tmp_path
    (tmp_path / name).write_text(json.dumps(payload))


def test_permitido_recibo_con_metricas_que_cumplen(tmp_path):
    _with_receipt(tmp_path, "G3_afirmabilidad.json", {"gate": "G3", "measured_at": "x", "by": "t",
        "metrics": {"queries": 24, "answered": 20, "abstained": 4, "affirmable": 19}})
    status, m = loop.gate_receipt(GATES["G3"], {})
    assert status == loop.PASS and m["rate"] == 0.95


def test_bloqueado_pass_escrito_a_mano_se_ignora(tmp_path):
    _with_receipt(tmp_path, "G3_afirmabilidad.json", {"gate": "G3", "pass": True, "status": "PASS",
        "metrics": {"queries": 24, "answered": 20, "abstained": 4, "affirmable": 2}})
    status, m = loop.gate_receipt(GATES["G3"], {})
    assert status == loop.FAIL, "el veredicto se recalcula desde las metricas, nunca se lee"


def test_bloqueado_sin_recibo_es_unknown_no_pass(tmp_path):
    loop.RECEIPTS = tmp_path
    status, m = loop.gate_receipt(GATES["G2"], {})
    assert status == loop.UNKNOWN and "sin recibo" in m["reason"]


def test_bloqueado_metricas_incompletas_es_unknown(tmp_path):
    _with_receipt(tmp_path, "G2_curacion.json", {"gate": "G2", "metrics": {"corpus_docs": 10}})
    status, m = loop.gate_receipt(GATES["G2"], {})
    assert status == loop.UNKNOWN and "ausentes" in m["reason"]


def test_bloqueado_muestra_insuficiente_falla(tmp_path):
    _with_receipt(tmp_path, "G4_falsos_bloqueos.json", {"gate": "G4", "metrics": {
        "queries": 5, "supported_claims": 50, "redacted_legitimate": 0, "annotator": "x"}})
    status, _ = loop.gate_receipt(GATES["G4"], {})
    assert status == loop.FAIL


def test_umbrales_del_plan_son_los_decididos_antes_de_medir():
    th = {g["id"]: g["thresholds"] for g in PLAN["gates"]}
    assert th["G1"]["fugas_max"] == 0
    assert th["G4"]["false_block_rate_max"] == 0.20
    assert th["G10"]["harmful_advice_max"] == 0 and th["G10"]["blinded"] is True
    assert PLAN["order_is_frozen"] is True
