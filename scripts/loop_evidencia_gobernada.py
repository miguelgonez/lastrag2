#!/usr/bin/env python3
"""
Loop de evidencia gobernada — NH-EG-LOOP-001
============================================
Un ciclo = medir TODAS las puertas del plan congelado, en su orden, y emitir
UNA siguiente accion. Nada aqui se marca a mano:

  · Las puertas `live` se miden ejecutando (suite, banco del verificador).
  · Las puertas `receipt` se RECALCULAN desde las metricas del recibo
    (evidencia_gobernada/receipts/<G>_*.json) contra los umbrales sellados;
    un campo "pass" escrito en el recibo se IGNORA.
  · Sin recibo = UNKNOWN. UNKNOWN != PASS.
  · Monotonia: una puerta que fue PASS y hoy no tiene recibo = FAIL
    (recibo desaparecido); PASS -> FAIL = regresion. Ambas paran el loop.
  · El plan se sella por sha256 en la primera ejecucion: si cambia, exit 1.

Exit: 0 todas PASS · 1 FAIL/regresion/plan alterado · 75 queda UNKNOWN
(se imprime la SIGUIENTE ACCION para el agente).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "bin" / "python"
EG = ROOT / "evidencia_gobernada"
RECEIPTS = EG / "receipts"
PLAN = EG / "PLAN_GATES.json"
STATE = EG / "STATE.json"

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_receipt(name: str) -> dict | None:
    p = RECEIPTS / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {"_malformed": True}


def m(rec: dict, key: str, default=None):
    return (rec.get("metrics") or {}).get(key, default)


# ---------------- medidores por puerta ----------------

def gate_G0(th: dict, state: dict) -> tuple[str, dict]:
    proc = subprocess.run([str(PY), "-m", "pytest", "tests/", "-q", "-p", "no:warnings",
                           "--tb=no"], cwd=ROOT, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    line = next((l for l in reversed(out.splitlines()) if "passed" in l or "no tests ran" in l), "")
    passed = int((re.search(r"(\d+) passed", line) or [0, 0])[1])
    failed = int((re.search(r"(\d+) failed", line) or [0, 0])[1])
    floor = max(th["tests_floor"], state.get("tests_floor", 0))
    metrics = {"passed": passed, "failed": failed, "floor": floor, "summary": line.strip()}
    if "no tests ran" in out or "INTERNALERROR" in out:
        return FAIL, {**metrics, "reason": "la suite no se ejecuto (recoleccion rota)"}
    if failed > th["failed_max"]:
        return FAIL, {**metrics, "reason": f"{failed} fallos"}
    if passed < floor:
        return FAIL, {**metrics, "reason": f"la suite ENCOGIO: {passed} < suelo {floor}"}
    state["tests_floor"] = passed  # el suelo solo sube
    return PASS, metrics


def gate_G1(th: dict, state: dict) -> tuple[str, dict]:
    sys.path.insert(0, str(ROOT))
    from core.rag.verifier import ClaimVerifier, run_verifier_benchmark
    local = asyncio.run(run_verifier_benchmark(ClaimVerifier()))
    metrics = {"lexical": {"fugas": local["fugas"], "falsos_bloqueos": local["falsos_bloqueos"],
                           "exact": local["exact"], "n": local["n"]}}
    if local["fugas"] > th["fugas_max"]:
        return FAIL, {**metrics, "reason": "fuga con metodo lexico"}
    rec = load_receipt("G1_juez_real.json")
    if rec is None:
        return UNKNOWN, {**metrics, "reason": "sin recibo de juez real (Spark/ALIA)"}
    judge = {"fugas": m(rec, "fugas"), "falsos_bloqueos": m(rec, "falsos_bloqueos"),
             "methods": m(rec, "methods"), "measured_at": rec.get("measured_at")}
    metrics["judge"] = judge
    if judge["fugas"] is None:
        return UNKNOWN, {**metrics, "reason": "recibo sin metrica fugas"}
    if judge["fugas"] > th["fugas_max"]:
        return FAIL, {**metrics, "reason": "fuga con juez real"}
    if not (judge["methods"] or {}).get("judge", "").startswith("applied"):
        return UNKNOWN, {**metrics, "reason": "el recibo no declara juez applied"}
    return PASS, metrics


def gate_receipt(gate: dict, state: dict) -> tuple[str, dict]:
    th, gid = gate["thresholds"], gate["id"]
    rec = load_receipt(gate["receipt"])
    if rec is None:
        return UNKNOWN, {"reason": f"sin recibo {gate['receipt']}"}
    if rec.get("_malformed"):
        return FAIL, {"reason": "recibo malformado"}
    mt = rec.get("metrics") or {}
    out = {"measured_at": rec.get("measured_at"), "by": rec.get("by"), "metrics": mt}

    def need(*keys):
        missing = [k for k in keys if mt.get(k) is None]
        return missing

    if gid == "G2":
        miss = need("corpus_docs", "checked_docs", "unknown", "max_check_age_days", "sources")
        if miss: return UNKNOWN, {**out, "reason": f"metricas ausentes {miss}"}
        cov = mt["checked_docs"] / max(1, mt["corpus_docs"])
        ok = (cov >= th["coverage_min"] and mt["unknown"] <= th["unknown_max"]
              and mt["max_check_age_days"] <= th["check_age_days_max"] and mt["sources"])
        return (PASS if ok else FAIL), {**out, "coverage": round(cov, 4)}
    if gid == "G3":
        miss = need("queries", "answered", "affirmable")
        if miss: return UNKNOWN, {**out, "reason": f"metricas ausentes {miss}"}
        if mt["queries"] < th["queries_min"]: return FAIL, {**out, "reason": "muestra insuficiente"}
        rate = mt["affirmable"] / max(1, mt["answered"])
        return (PASS if rate >= th["affirmable_rate_min"] else FAIL), {**out, "rate": round(rate, 4)}
    if gid == "G4":
        miss = need("queries", "supported_claims", "redacted_legitimate", "annotator")
        if miss: return UNKNOWN, {**out, "reason": f"metricas ausentes {miss}"}
        if mt["queries"] < th["queries_min"]: return FAIL, {**out, "reason": "muestra insuficiente"}
        rate = mt["redacted_legitimate"] / max(1, mt["supported_claims"])
        return (PASS if rate <= th["false_block_rate_max"] else FAIL), {**out, "rate": round(rate, 4)}
    if gid == "G5":
        miss = need("questions", "no_evidence_by_corpus")
        if miss: return UNKNOWN, {**out, "reason": f"metricas ausentes {miss}"}
        if mt["questions"] < th["questions_min"]: return FAIL, {**out, "reason": "muestra insuficiente"}
        rate = mt["no_evidence_by_corpus"] / mt["questions"]
        return (PASS if rate <= th["no_evidence_by_corpus_rate_max"] else FAIL), {**out, "rate": round(rate, 4)}
    if gid == "G6":
        miss = need("recall_at_20", "p50_ms", "gold_sha256")
        if miss: return UNKNOWN, {**out, "reason": f"metricas ausentes {miss}"}
        ok = mt["recall_at_20"] >= th["recall_at_20_min"] and mt["p50_ms"] <= th["p50_ms_max"]
        return (PASS if ok else FAIL), out
    if gid == "G7":
        miss = need("items", "kappa")
        if miss: return UNKNOWN, {**out, "reason": f"metricas ausentes {miss}"}
        ok = mt["items"] >= th["items_min"] and mt["kappa"] >= th["kappa_min"]
        return (PASS if ok else FAIL), out
    if gid == "G8":
        miss = need("hours")
        if miss: return UNKNOWN, {**out, "reason": f"metricas ausentes {miss}"}
        return (PASS if mt["hours"] <= th["retraction_reflect_hours_max"] else FAIL), out
    if gid == "G9":
        miss = need("queries", "p50_s", "layers_active")
        if miss: return UNKNOWN, {**out, "reason": f"metricas ausentes {miss}"}
        ok = (mt["queries"] >= th["queries_min"] and mt["p50_s"] <= th["p50_s_max"]
              and set(th["layers_required"]) <= set(mt["layers_active"]))
        return (PASS if ok else FAIL), out
    if gid == "G10":
        miss = need("protocol_sha256", "questions", "blinded", "external_evaluators",
                    "correctness_noninferior", "citation_verifiability_superior", "harmful_advice")
        if miss: return UNKNOWN, {**out, "reason": f"metricas ausentes {miss}"}
        ok = (mt["questions"] >= th["questions_min"] and mt["blinded"] is True
              and mt["external_evaluators"] is True and mt["correctness_noninferior"] is True
              and mt["citation_verifiability_superior"] is True
              and mt["harmful_advice"] <= th["harmful_advice_max"])
        return (PASS if ok else FAIL), out
    if gid == "G11":
        miss = need("intended_use_signed", "signed_by", "date")
        if miss: return UNKNOWN, {**out, "reason": f"metricas ausentes {miss}"}
        return (PASS if mt["intended_use_signed"] is True else FAIL), out
    if gid == "G12":
        miss = need("auditor", "independent", "fugas_reproduced", "report_sha256")
        if miss: return UNKNOWN, {**out, "reason": f"metricas ausentes {miss}"}
        ok = mt["independent"] is True and mt["fugas_reproduced"] <= th["fugas_reproduced_max"]
        return (PASS if ok else FAIL), out
    return UNKNOWN, {**out, "reason": "puerta sin medidor"}


# ---------------- ciclo ----------------

def main() -> int:
    log: list[str] = []

    def say(s: str):
        print(s); log.append(s)

    say(f"=== Loop evidencia gobernada · {datetime.now().isoformat(timespec='seconds')} ===")
    plan = json.loads(PLAN.read_text())
    state = json.loads(STATE.read_text()) if STATE.exists() else {"passes": 0, "history": [], "best": {}}

    plan_sha = sha256(PLAN)
    if state.get("plan_sha256") is None:
        state["plan_sha256"] = plan_sha
        say(f"🔒 plan sellado: {plan_sha[:12]}… (umbrales congelados ANTES de medir)")
    elif state["plan_sha256"] != plan_sha:
        say("❌ el plan cambio tras el sellado. Cambiar umbrales exige version nueva + "
            "decision del PI + re-sellado deliberado (borrar STATE.json). PARADO.")
        _persist(state, log, {}, 1); return 1

    results: dict[str, dict] = {}
    stop_reason = None
    for gate in plan["gates"]:
        gid = gate["id"]
        if gid == "G0":
            status, metrics = gate_G0(gate["thresholds"], state)
        elif gid == "G1":
            status, metrics = gate_G1(gate["thresholds"], state)
        else:
            status, metrics = gate_receipt(gate, state)
        # monotonia
        best = state["best"].get(gid)
        if best == PASS and status == UNKNOWN:
            status, metrics = FAIL, {**metrics, "reason": "RECIBO DESAPARECIDO: fue PASS"}
        if best == PASS and status == FAIL:
            metrics = {**metrics, "regresion": True}
        if status == PASS:
            state["best"][gid] = PASS
        results[gid] = {"name": gate["name"], "status": status, "needs_pi": gate.get("needs_pi", False),
                        "metrics": metrics}
        icon = {"PASS": "✅", "FAIL": "❌", "UNKNOWN": "⬜"}[status]
        say(f"{icon} {gid:4s} {gate['name']:22s} {status:8s} {metrics.get('reason', '') if status != PASS else ''}")
        if status == FAIL and gid in ("G0", "G1"):
            stop_reason = f"{gid} FAIL: nada por encima es creible"; break

    n_pass = sum(1 for r in results.values() if r["status"] == PASS)
    n_fail = sum(1 for r in results.values() if r["status"] == FAIL)
    total = len(plan["gates"])
    say(f"\n=== {n_pass}/{total} PASS · {n_fail} FAIL · {total - n_pass - n_fail} UNKNOWN ===")

    if n_fail or stop_reason:
        say(f"❌ PARAR: {stop_reason or 'hay puertas FAIL (ver arriba)'}")
        rc = 1
    elif n_pass == total:
        state["passes"] = state.get("passes", 0) + 1
        say(f"🎯 TODAS las puertas PASS. Pasadas verdes consecutivas: {state['passes']}. "
            f"Limites: {plan['claim_limits']}")
        rc = 0
    else:
        state["passes"] = 0
        nxt = next(g for g in plan["gates"] if results.get(g["id"], {}).get("status") != PASS)
        say("\n>>> SIGUIENTE ACCION (una sola; el loop re-mide al terminar) <<<")
        say(f"puerta   : {nxt['id']} · {nxt['name']}")
        say(f"producir : {nxt['produce']}")
        if nxt.get("receipt"):
            say(f"recibo   : evidencia_gobernada/receipts/{nxt['receipt']}  "
                f"(schema: {{gate, measured_at, by, inputs_sha256, metrics{{...}}}}; sin campo pass)")
        say(f"umbrales : {json.dumps(nxt['thresholds'], ensure_ascii=False)}")
        if nxt.get("needs_pi"):
            say(f"⚠️ DECISION DEL PI REQUERIDA ANTES: {nxt.get('pi_decision')}")
        say("prohibido: mocks, bajar umbrales, escribir 'pass' a mano, tocar recibos de "
            "puertas anteriores, tocar PLAN_GATES.json")
        rc = 75
    _persist(state, log, results, rc)
    return rc


def _persist(state: dict, log: list[str], results: dict, rc: int) -> None:
    EG.mkdir(exist_ok=True)
    rec = {"at": datetime.now().isoformat(timespec="seconds"), "rc": rc,
           "gates": {k: v["status"] for k, v in results.items()}}
    state.setdefault("history", []).append(rec)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    (EG / "LOOP_LOG.txt").write_text("\n".join(log) + "\n")
    lines = [f"# SCORECARD evidencia gobernada — {rec['at']} (rc={rc})",
             f"Plan sellado: `{state.get('plan_sha256', '')[:16]}…`\n",
             "| puerta | nombre | estado | detalle |", "|---|---|---|---|"]
    for gid, r in results.items():
        det = r["metrics"].get("reason") or (
            {k: v for k, v in r["metrics"].items() if k in ("rate", "coverage", "summary", "lexical", "judge")} or "")
        lines.append(f"| {gid} | {r['name']} | {r['status']} | {det} |")
    (EG / "SCORECARD.md").write_text("\n".join(lines) + "\n")
    (EG / "SCORECARD.json").write_text(json.dumps({"at": rec["at"], "rc": rc, "results": results},
                                                  ensure_ascii=False, indent=2, default=str) + "\n")


if __name__ == "__main__":
    sys.exit(main())
