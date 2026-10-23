#!/usr/bin/env python3
"""Tests del resolver de sociedades acreditadas (curation/societies.py).

Cada control verifica caso POSITIVO (en lista => True) y caso UNKNOWN
(no en lista / vacío => None). Nada devuelve False por matching.
Ejecutable sin pytest: python3 tests/test_societies_resolver.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curation.societies import resolve_accredited, curation_hint, load_societies

PASS, FAIL = [], []


def check(nombre, condicion, detalle=""):
    (PASS if condicion else FAIL).append(nombre)
    print(("  ✅" if condicion else "  ❌") + f" {nombre}" + (f" — {detalle}" if not condicion else ""))


print("resolver de sociedades acreditadas (regla PI 23-oct: sin lista => UNKNOWN)")

# ── positivos: nombradas por el PI ──
check("SED (acrónimo del PI) => True", resolve_accredited("SED") is True)
check("Sociedad Española de Diabetes (nombre completo) => True",
      resolve_accredited("Sociedad Española de Diabetes") is True)
check("SED con paréntesis estilo registro => True",
      resolve_accredited("Sociedad Española de Diabetes (SED)") is True)
check("ESC => True", resolve_accredited("ESC") is True)
check("European Society of Cardiology => True",
      resolve_accredited("European Society of Cardiology") is True)
check("semFYC (minúsculas) => True", resolve_accredited("semfyc") is True)
check("Sociedad Española de Medicina Familiar y Comunitaria => True",
      resolve_accredited("Sociedad Española de Medicina de Familia y Comunitaria") is True)

# ── positivos: representativas del catálogo ──
check("SEMERGEN => True", resolve_accredited("SEMERGEN") is True)
check("Sociedad Española de Cardiología (SEC) => True",
      resolve_accredited("Sociedad Española de Cardiología (SEC)") is True)
check("SEOM => True", resolve_accredited("SEOM") is True)

# ── acentos y variantes ──
check("nombre sin acentos casaa con lista acentuada => True",
      resolve_accredited("sociedad espanola de diabetes") is True)

# ── UNKNOWN: lo que NO está en la lista no afirma ──
check("Sociedad Inventada de Prueba => None (UNKNOWN)",
      resolve_accredited("Sociedad Inventada de Prueba") is None)
check("Asociación de Pacientes X => None", resolve_accredited("Asociación de Pacientes X") is None)
check("editor vacío => None", resolve_accredited("") is None)
check("editor None => None", resolve_accredited(None) is None)
check("grupo no-sociedad (redGDPS) => None", resolve_accredited("redGDPS") is None)

# ── ambigüedades blindadas ──
check("SEEN solo (acrónimo ambiguo) => None: exige nombre completo",
      resolve_accredited("SEEN") is None)
check("SEEN Endocrinología completa => True",
      resolve_accredited("Sociedad Española de Endocrinología y Nutrición") is True)
check("SEEN Enfermería Neonatal completa => True",
      resolve_accredited("Sociedad Española de Enfermería Neonatal") is True)
check("SER solo (acrónimo palabra común) => None",
      resolve_accredited("SER") is None)
check("Reumatología completa => True",
      resolve_accredited("Sociedad Española de Reumatología") is True)

# ── jamás False por matching ──
check("ningún editor devuelve False por matching",
      all(resolve_accredited(x) is not False for x in
          ["SED", "ESC", "Sociedad Inventada", "", None, "redGDPS", "SEEN"]))

# ── integración con capa 5 ──
hint = curation_hint("Sociedad Española de Diabetes (SED)")
check("curation_hint: tier=clinical_guideline + accredited=True",
      hint == {"tier": "clinical_guideline",
               "publisher": "Sociedad Española de Diabetes (SED)",
               "accredited": True})
hint2 = curation_hint("Asociación Cualquiera")
check("curation_hint: accredited=None alimenta GUIDELINE_ACCREDITATION_UNKNOWN",
      hint2["accredited"] is None and hint2["tier"] == "clinical_guideline")

# ── integridad de la lista ──
soc = load_societies()
check("lista carga y tiene >= 45 sociedades", len(soc) >= 45, f"tenemos {len(soc)}")
check("toda entrada tiene name + basis",
      all(s.get("name") and s.get("basis") for s in soc))

print(f"\n{len(PASS)} PASS · {len(FAIL)} FAIL")
sys.exit(1 if FAIL else 0)
