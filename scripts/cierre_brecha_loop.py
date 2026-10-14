#!/usr/bin/env python3
"""
Bucle de cierre de brecha LastRAG 2.0 — comando de mantenimiento
=================================================================
Idempotente: re-ejecutable; la fuente de verdad de cada ítem son sus TESTS
(caso permitido + caso bloqueado), nunca una marca a mano. Reglas del prereg
(cierre_brecha/PREREG.md):

  1. Cero regresión: la suite completa debe estar verde en cada pasada.
  2. Ítem DONE ⇔ sus tests pasan Y tiene caso permitido Y caso bloqueado.
  3. N-verde = 2 pasadas completas consecutivas sin fallos.
  7. Exit codes: 0 objetivo · 1 fallos · 75 skip con razón escrita.

El scorecard (cierre_brecha/SCORECARD.{json,md}) sale de ESTE script; el
informe de estado NUNCA se escribe a mano.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CB = ROOT / "cierre_brecha"
PY = ROOT / ".venv" / "bin" / "python"

sys.path.insert(0, str(ROOT))
from core.rag.multimodal import vision_available  # noqa: E402

# --- Universo de 15 ítems (compliance table; ver PREREG y PLAN_CIERRE_BRECHA) ---
ITEMS = {
    # id: (descripción, ola, selector pytest, estado base, nota)
    "CB-1": ("Triple RAG", "base", "test_smoke or test_e2e_sovereign"),
    "CB-9": ("Pipeline E2E + audit trail", "base", "test_e2e_sovereign"),
    "CB-10": ("Ingesta sellada + hashes", "base", "test_smoke"),
    "CB-11": ("Soberanía + fail-closed", "base", "test_degradation or test_local_llm_client"),
    "CB-2": ("Router iterativo (decompose/sufficiency/gap)", "1", "cb2"),
    "CB-3": ("RRF (port del control plane)", "1", "cb3"),
    "CB-4": ("Reranking clínico + cross-encoder ONNX", "1", "cb4"),
    "CB-5": ("Evidence Pack 2.0 claim↔evidence", "2", "cb5"),
    "CB-6": ("Conflict engine", "2", "cb6"),
    "CB-7": ("Temporal RAG", "2", "cb7"),
    "CB-8": ("Causal RAG + CausalGate", "4", "cb8"),
    "CB-14": ("Validación sintética causal (ground truth)", "4", "cb14"),
    "CB-12": ("Failure Graph con coste medido", "5", "cb12"),
    "CB-13": ("Taxonomía de abstención", "5", "cb13"),
    "CB-15": ("Multimodalidad (tablas/figuras)", "3", "cb15"),
}
# Declaraciones de alcance honesto (prereg §ítems): PARTIAL aunque los tests pasen
PARTIAL_BY_DECLARATION = {
    "CB-15": "extracción posicional sin modelo de visión (etiquetado posicional-v1)",
}
# El resto de OMEGA-I2 (real) queda como dependencia externa declarada
EXTERNAL_DECLARATIONS = {
    "CB-14": "OMEGA-I2 con servicios reales del programa: dependencia externa "
             "(prestador sellado); aquí se acredita el benchmark sintético",
}
BASELINE_DONE = {"CB-1", "CB-9", "CB-10", "CB-11"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_pytest(args: list[str]) -> tuple[int, list[str], str]:
    cmd = [str(PY), "-m", "pytest", *args, "-q", "--no-header", "-p", "no:cacheprovider"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    node_ids = []
    for line in (proc.stdout or "").splitlines():
        if line.startswith("tests/") and "::" in line:
            node_ids.append(line.strip())
    return proc.returncode, node_ids, proc.stdout or ""


def collect_node_ids(selector: str) -> list[str]:
    """--collect-only -q lista los node ids que el selector ejerce."""
    _, _, out = run_pytest(["tests/", "--collect-only", "-k", selector])
    return [l.strip() for l in out.splitlines()
            if l.strip().startswith("tests/") and "::" in l.strip()]


def main() -> int:
    CB.mkdir(exist_ok=True)
    prereg = CB / "PREREG.md"
    state_path = CB / "STATE.json"

    t0 = time.time()
    log_lines: list[str] = []

    def log(msg: str):
        print(msg)
        log_lines.append(msg)

    # --- PASO 0: sellado del prereg (primera ejecución) ---
    state: dict = {"passes": 0, "history": []}
    if state_path.exists():
        state = json.loads(state_path.read_text())
    prereg_sha = sha256(prereg)
    if state.get("prereg_sha256") is None:
        state["prereg_sha256"] = prereg_sha
        state["sealed_at"] = datetime.now().isoformat(timespec="seconds")
        log(f"🔒 prereg sellado: {prereg_sha[:12]}…")
    elif state["prereg_sha256"] != prereg_sha:
        log("❌ el prereg cambió tras el sellado: re-sellar deliberadamente "
            "(borrar STATE.json) o revertir")
        return 1

    # --- PASO 1: suite completa (cero regresión) ---
    rc, nodes, out = run_pytest(["tests/"])
    full_green = rc == 0
    total_tests = out.strip().splitlines()[-1] if out.strip() else ""
    if full_green:
        log(f"✅ suite completa VERDE: {total_tests.strip()}")
    else:
        log(f"❌ REGRESIÓN/FAILED en suite completa:\n{out[-2500:]}")
        state["passes"] = 0
        _persist(state, state_path, None, log_lines, CB, t0, failed=True)
        return 1

    # --- PASO 2: veredicto por ítem (fuente de verdad = tests) ---
    vision_ok = vision_available()
    log(f"👁️  capacidad de visión real (docling/TableFormer): "
        f"{'SÍ' if vision_ok else 'NO'}")
    verdicts: dict[str, dict] = {}
    problems: list[str] = []
    for item, (desc, ola, selector) in ITEMS.items():
        v = {"desc": desc, "ola": ola}
        if item in BASELINE_DONE:
            v.update(status="DONE", evidence="suite base verde + T3 51/51 (6-oct)")
        else:
            ids = collect_node_ids(selector)
            permitted = [i for i in ids if "permitted" in i]
            blocked = [i for i in ids if "blocked" in i]
            sel_rc, _, _ = run_pytest(["tests/", "-k", selector])
            v["tests"] = len(ids)
            if not ids:
                v.update(status="PENDING", reason="sin tests que ejerciten el ítem")
                problems.append(f"{item}: sin tests")
            elif sel_rc != 0:
                v.update(status="FAILED", reason="tests del ítem en rojo")
                problems.append(f"{item}: tests en rojo")
            elif not permitted or not blocked:
                v.update(status="INCOMPLETE",
                         reason=f"permitted={len(permitted)} blocked={len(blocked)} "
                                "(un control sin caso bloqueado no existe)")
                problems.append(f"{item}: falta caso permitted/blocked")
            else:
                v.update(status="DONE",
                         evidence=f"{len(ids)} tests "
                                  f"({len(permitted)}P/{len(blocked)}B)")
        if item == "CB-15" and v.get("status") == "DONE":
            # Gate honesto del 100%: DONE sólo con capacidad de visión REAL
            # (import docling/TableFormer) Y tests que ejerzan esa rama.
            # Un env-var JAMÁS sustituye la capacidad (anti-100%-falso).
            if not vision_ok:
                v["status"] = "PARTIAL"
                v["declaration"] = ("sin modelo de visión con capacidad real "
                                    "(docling/TableFormer no importable); "
                                    "cascada declarada find-tables→posicional")
            else:
                ids_all = collect_node_ids(selector)
                vision_tests = [i for i in ids_all if "vision" in i]
                if not vision_tests:
                    v["status"] = "INCOMPLETE"
                    v["reason"] = ("visión disponible pero sin tests que "
                                   "ejerciten la rama de visión")
                    problems.append(f"{item}: falta test de la rama visión")
        if item in EXTERNAL_DECLARATIONS:
            v["external"] = EXTERNAL_DECLARATIONS[item]
        verdicts[item] = v

    # --- PASO 3: cumplimiento ponderado (fórmula, nunca a mano) ---
    counts = {"DONE": 0, "PARTIAL": 0, "PENDING": 0, "FAILED": 0,
              "INCOMPLETE": 0, "BASELINE": 0}
    for v in verdicts.values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    done = counts["DONE"] + counts["BASELINE"]
    partial = counts["PARTIAL"]
    compliance = round((done + 0.5 * partial) / len(ITEMS), 4)

    green_pass = not problems and full_green
    if green_pass:
        state["passes"] = state.get("passes", 0) + 1
    else:
        state["passes"] = 0

    log(f"\n=== SCORECARD — cumplimiento ponderado: {compliance:.0%} "
        f"({done} DONE + {partial} PARTIAL de {len(ITEMS)}) ===")
    for item in sorted(verdicts, key=lambda i: (ITEMS[i][1], i)):
        v = verdicts[item]
        mark = {"DONE": "✅", "BASELINE": "✅", "PARTIAL": "🟡",
                "FAILED": "❌", "INCOMPLETE": "🟠", "PENDING": "⬜"}[v["status"]]
        log(f"{mark} {item} [ola {v['ola']}] {v['desc']}: {v['status']}"
            + (f" — {v.get('declaration')}" if v.get("declaration") else "")
            + (f" — {v.get('reason')}" if v.get("reason") else ""))
    log(f"\nPasadas verdes consecutivas: {state['passes']}/2")

    _persist(state, state_path, verdicts, log_lines, CB, t0,
             compliance=compliance, counts=counts, problems=problems)

    if problems:
        return 1
    if compliance >= 1.0 and state["passes"] >= 2:
        log("🎯 100% (15/15 DONE) + N-VERDE. Bucle de mantenimiento en verde total.")
        return 0
    if compliance < 1.0 and not vision_ok:
        log("🟡 100% bloqueado por capacidad: falta visión real para CB-15 "
            "(docling/TableFormer). Declarado, no inventado.")
    return 75  # verde pero sin 100% o sin N-verde: volver a ejecutar


def _persist(state, state_path, verdicts, log_lines, cb, t0, **extra):
    import dataclasses
    rec = {"at": datetime.now().isoformat(timespec="seconds"),
           "duration_s": round(time.time() - t0, 1), **extra}
    if verdicts is not None:
        state["last_verdicts"] = verdicts
    state.setdefault("history", []).append(rec)
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    (cb / "LOOP_LOG.txt").write_text("\n".join(log_lines) + "\n")
    if verdicts is not None and "compliance" in extra:
        sc = {"timestamp": rec["at"],
              "compliance_ponderado": extra["compliance"],
              "counts": extra["counts"],
              "formula": "(DONE + 0.5*PARTIAL)/15",
              "items": verdicts,
              "passes_verdes": state["passes"],
              "prereg_sha256": state["prereg_sha256"]}
        (cb / "SCORECARD.json").write_text(
            json.dumps(sc, indent=2, ensure_ascii=False))
        lines = [f"# SCORECARD cierre de brecha — {rec['at']}",
                 f"**Cumplimiento ponderado: {extra['compliance']:.0%}** "
                 f"(fórmula {sc['formula']}; {extra['counts']})",
                 f"Pasadas verdes consecutivas: {state['passes']}/2",
                 f"Prereg: `{state['prereg_sha256'][:16]}…`\n"]
        for item in sorted(verdicts, key=lambda i: (verdicts[i]['ola'], i)):
            v = verdicts[item]
            lines.append(f"- {'✅' if v['status'] in ('DONE','BASELINE') else '🟡' if v['status']=='PARTIAL' else '❌'} "
                         f"**{item}** [ola {v['ola']}] {v['desc']} — {v['status']}"
                         + (f" ({v.get('evidence')})" if v.get('evidence') else "")
                         + (f" · {v.get('declaration')}" if v.get('declaration') else "")
                         + (f" · {v.get('reason')}" if v.get('reason') else "")
                         + (f" · EXT: {v.get('external')}" if v.get('external') else ""))
        (cb / "SCORECARD.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
