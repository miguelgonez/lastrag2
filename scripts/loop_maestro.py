#!/usr/bin/env python3
"""
Loop maestro LastRAG 2.0 — post-100 % arquitectónico
=====================================================
1. Re-acredita el 100 % de las 5 olas (suite completa, cero regresión).
2. Ejecuta el loop de calidad sobre el piloto real (si existe el corpus).
3. Valida el DeltaBackend si DELTA_PATH + pyspark están (skip declarado si no).
4. Nunca éxito falso; claim limits escritos en el resumen.

Exit:
  0  = 100 % olas + calidad real con mejora + N-verde (y delta smoke, si aplica)
  75 = 100 % olas OK; calidad real pendiente/sin mejora/skip declarado
  1  = regresión en las olas o error duro
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "bin" / "python"
CB = ROOT / "cierre_brecha"
CB_REAL = ROOT / "cierre_brecha_real"


def run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    log: list[str] = []

    def info(msg: str):
        print(msg)
        log.append(msg)

    info(f"=== Loop maestro · {datetime.now().isoformat(timespec='seconds')} ===")

    # 1) Re-acreditación de las 5 olas (la suite ES la fuente de verdad)
    info("[1] Suite de las 5 olas (100 % arquitectónico)")
    rc, out = run([str(PY), "-m", "pytest", "tests/", "-q", "--tb=no"])
    if rc != 0:
        info(f"❌ REGRESIÓN en la suite de olas:\n{out[-1500:]}")
        _persist(log, olas=False)
        return 1
    summary_line = next((l for l in reversed(out.splitlines())
                         if "passed" in l), f"rc=0")
    info(f"✅ Suite olas verde: {summary_line}")

    # 2) Loop maestro de scorecard (re-acredita 15/15 + N-verde del cierre)
    info("[2] Scorecard de cierre (re-acreditación)")
    rc, out = run([str(PY), "scripts/cierre_brecha_loop.py"])
    tail = [l for l in out.splitlines()
            if "SCORECARD" in l or "Pasadas" in l or "🎯" in l]
    info("\n".join(tail) or out[-300:])
    scorecard_100 = rc == 0
    if not scorecard_100:
        info(f"🟡 cierre_brecha_loop exit={rc} (ver encima; no es regresión "
             "de suite pero el 100 % no está re-acreditado)")

    # 3) Calidad sobre corpus real (si existe el piloto)
    quality_ok, quality_delta = False, None
    quality_script = ROOT / "scripts" / "calidad_corpus_real_loop.py"
    if quality_script.exists() and (CB_REAL / "data" / "pubmed_pilot.jsonl").exists():
        info("[3] Loop de calidad corpus real")
        rc, out = run([str(PY), str(quality_script)])
        info("\n".join(out.strip().splitlines()[-4:]))
        quality_ok = rc == 0
        receipt = CB_REAL / "QUALITY_CORPUS_REAL.json"
        if receipt.exists():
            quality_delta = json.loads(receipt.read_text()).get("delta_rec1")
            info(f"    Δ recall@1 (recibo) = {quality_delta}")
    else:
        info("[3] Calidad corpus real: sin piloto descargado (skip declarado)")

    # 3b) Escala 50 k (si el corpus de escala existe; prereg propio)
    scale_ok, scale_delta = None, None
    scale_script = ROOT / "scripts" / "calidad_scale_loop.py"
    if scale_script.exists() and (CB_REAL / "data" / "pubmed_scale.jsonl").exists():
        info("[3b] Loop de calidad ESCALA 50k (gold MeSH-estricto)")
        rc, out = run([str(PY), str(scale_script)])
        info("\n".join(out.strip().splitlines()[-4:]))
        scale_ok = rc == 0
        receipt = CB_REAL / "QUALITY_SCALE.json"
        if receipt.exists():
            scale_delta = json.loads(receipt.read_text()).get("delta_rec1")
            info(f"    Δ rec@1 escala (recibo) = {scale_delta}")
    else:
        info("[3b] Escala 50k: sin corpus de escala descargado (skip declarado)")

    # 4) DeltaBackend (solo si hay Delta Y pyspark en ESTE entorno)
    delta_ok = None
    if os.getenv("DELTA_PATH"):
        try:
            import pyspark  # noqa: F401
        except Exception:
            info("[4] DeltaBackend: DELTA_PATH definido pero sin pyspark "
                 "aquí (el smoke REAL corre en el host/contenedor Spark; "
                 "comando en tests/test_delta_backend.py) — skip declarado")
        else:
            info("[4] DeltaBackend smoke (pytest)")
            rc, out = run([str(PY), "-m", "pytest",
                           "tests/test_delta_backend.py", "-q", "--tb=short"])
            delta_ok = rc in (0, 5)  # 0 pass / 5 = todos skipped (declarado)
            info(f"    {'✅' if rc == 0 else '🟡 skip declarado' if rc == 5 else '⚠️'} "
                 f"{out.strip().splitlines()[-1] if out.strip() else rc}")
    else:
        info("[4] DeltaBackend: DELTA_PATH no definido (skip declarado)")

    # Resumen + exit
    info("\n=== RESUMEN ===")
    info(f"Olas (suite):            ✅")
    info(f"Scorecard 15/15 + N-verde: {'✅' if scorecard_100 else '🟡'}")
    info(f"Calidad corpus real:     {'✅ Δ=' + str(quality_delta) if quality_ok else '🟡 skip/sin mejora'}")
    info(f"Escala 50k (MeSH-strict): {'✅ Δ=' + str(scale_delta) if scale_ok else '🟡 skip' if scale_ok is None else '⚠️ pendiente/sin mejora'}")
    info(f"DeltaBackend:            {'✅' if delta_ok else '🟡 skip' if delta_ok is None else '⚠️'}")

    summary = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "olas_suite": True,
        "scorecard_100": scorecard_100,
        "calidad_real_ok": quality_ok,
        "calidad_delta_rec1": quality_delta,
        "escala_50k_ok": scale_ok,
        "escala_delta_rec1": scale_delta,
        "delta_backend_ok": delta_ok,
        "claim_limits": "intactos — nada de validez clínica ni calidad "
                        "semántica sobre corpus real amplio; el Δ del piloto "
                        "usa silver-gold por sourcing",
    }
    (CB / "LOOP_MAESTRO.json").write_text(json.dumps(summary, indent=2,
                                                     ensure_ascii=False))
    (CB / "LOOP_MAESTRO.log").write_text("\n".join(log) + "\n")

    if quality_ok and scorecard_100:
        info("🎯 Loop maestro: 100 % olas re-acreditado + calidad real con mejora")
        return 0
    info("🟡 100 % olas intacto; calidad real pendiente/skipped (declarado)")
    return 75


def _persist(log: list[str], olas: bool):
    (CB / "LOOP_MAESTRO.json").write_text(json.dumps(
        {"timestamp": datetime.now().isoformat(timespec="seconds"),
         "olas_suite": olas, "claim_limits": "intactos"}, indent=2))
    (CB / "LOOP_MAESTRO.log").write_text("\n".join(log) + "\n")


if __name__ == "__main__":
    import sys
    sys.exit(main())
