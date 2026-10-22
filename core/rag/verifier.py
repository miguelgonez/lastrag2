"""
LastRAG 2.0 Foundation — Verificador claim ↔ evidencia (grado médico, capa 4)
=============================================================================
La capa 3 (`grounding.py`) ancla DATOS DUROS y CITAS TEXTUALES de forma
literal. Esta capa cierra el hueco que aquella declaraba: las afirmaciones
PARAFRASEADAS, sin cifras ni comillas, que antes pasaban «por ausencia de
material verificable».

Cada frase asertiva de la respuesta se convierte en un *claim* y se busca su
respaldo en la evidencia CONGELADA (misma `EvidenceFreeze` de la capa 3, mismo
`evidence_hash`). El veredicto por claim es uno de:

  SUPPORTED     — respaldado por un fragmento concreto (se devuelve el span).
  UNSUPPORTED   — no se encontró respaldo suficiente: la frase se RETIRA.
  CONTRADICTED  — la evidencia dice lo contrario (dirección opuesta sobre el
                  mismo desenlace, o el juez lo determina): la respuesta
                  completa se RETIENE — un modelo que invierte la evidencia
                  no merece confianza parcial.
  META          — frase sin contenido verificable (encabezados, conectores,
                  rechazos de dominio, aparato de citas): no cuenta.

Tres métodos, de menor a mayor fuerza, TODOS declarados en el informe con su
disponibilidad real (un método no disponible se declara UNAVAILABLE, nunca se
simula):

  lexical   — siempre. Solapamiento de términos de contenido con tolerancia
              morfológica (prefijo-6, como el anclaje suave de AESPLA-PRL)
              + detección de polaridad (negación) y dirección (↑/↓).
  semantic  — si se inyecta un embedder (p. ej. FastEmbed multilingüe):
              coseno claim↔frase de evidencia. Similitud NO es implicación:
              por eso nunca decide sola y nunca anula una contradicción.
  judge     — si se inyecta un LLM soberano: pregunta MCQ (A respalda / B
              contradice / C no determinable), fail-closed: C o ilegible =
              NO respaldado; error = método UNAVAILABLE declarado.

Regla de oro (grado médico): la verificación optimiza el RECALL de lo no
respaldado — es preferible retirar una paráfrasis legítima a entregar una
afirmación inventada. Los falsos bloqueos se miden y se declaran; las fugas
no se toleran (ver `run_verifier_benchmark`).

Lo que NO hace: no juzga veracidad clínica del corpus (si la evidencia es
falsa, un claim «respaldado» sigue siendo falso) ni sustituye la revisión
humana. Lo dice el informe, no la letra pequeña.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional, Sequence

from .conflict import _direction
from .grounding import EvidenceFreeze, _norm, split_sentences

Embedder = Callable[[Sequence[str]], list[list[float]]]

SUPPORTED, UNSUPPORTED, CONTRADICTED, META = (
    "SUPPORTED", "UNSUPPORTED", "CONTRADICTED", "META")

REDACTION_MARK = "「afirmación retirada: sin respaldo en la evidencia recuperada」"

# ── Léxico ───────────────────────────────────────────────────────────────
_STOP = {
    "para", "como", "cual", "cuales", "este", "esta", "estos", "estas", "esto",
    "pero", "porque", "cuando", "donde", "sobre", "entre", "desde", "hasta",
    "puede", "pueden", "deben", "debe", "tiene", "tienen", "segun", "tambien",
    "aunque", "mientras", "ademas", "todo", "toda", "todos", "todas", "otro",
    "otra", "otros", "otras", "mismo", "misma", "cada", "muy", "mas", "menos",
    "solo", "sin", "con", "por", "del", "los", "las", "una", "uno", "unos",
    "unas", "que", "con", "ser", "son", "esta", "estan", "hay", "fue", "han",
    "sido", "sus", "ello", "ella", "ellos", "ellas", "nos", "les", "hacia",
    "ante", "bajo", "tras", "durante", "mediante", "respecto", "caso", "casos",
    "forma", "manera", "modo", "tipo", "parte", "general", "generalmente",
    "habitualmente", "principalmente", "especialmente", "ademas", "asi",
    "entonces", "luego", "aqui", "alli", "ahi", "siguiente", "siguientes",
}
_NEGATION = re.compile(r"\b(no|nunca|jamas|tampoco|ningun[ao]?s?|ni)\b")
_META_OPENERS = (
    "a continuacion", "en resumen", "en conclusion", "segun la evidencia",
    "la evidencia proporcionada", "basada en la evidencia", "basado en la evidencia",
    "respuesta:", "resumen:", "conclusion:", "en sintesis", "cabe destacar",
    "es importante", "lo siento", "no puedo responder", "soy un asistente",
    "consulta a un profesional", "consulte a su medico", "consulte con su medico",
)
_SKIP_MARKS = ("⛔", "「", "⚠️", "###", "## ", "# ", "```", "|")
_CITATION_LINE = re.compile(r"^\s*[-•*]?\s*[^:]{2,80}\s·\s.+$")  # "Guia · 3.2 · p.43"
_MIN_CONTENT_TERMS = 3


def content_terms(text: str) -> list[str]:
    norm = _norm(text)
    out = []
    for tok in re.findall(r"[a-z0-9]{3,}", norm):
        if tok in _STOP:
            continue
        out.append(tok)
    return out


def _stem(tok: str) -> str:
    return tok[:6] if len(tok) > 6 else tok


def _overlap(claim_terms: list[str], frag_terms: set[str]) -> float:
    """Fracción de términos del claim presentes en el fragmento, con
    tolerancia morfológica por prefijo (planificar/planifica…). Los números
    deben coincidir exactos."""
    if not claim_terms:
        return 0.0
    frag_stems = {_stem(t) for t in frag_terms}
    hit = 0
    for t in claim_terms:
        if t.isdigit():
            hit += t in frag_terms
        else:
            hit += (t in frag_terms) or (_stem(t) in frag_stems)
    return hit / len(claim_terms)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a)) or 1.0
    db = math.sqrt(sum(y * y for y in b)) or 1.0
    return num / (da * db)


def _letter(decision: str) -> str:
    cleaned = (decision or "").strip().strip("*_\"'«»` \t\n\r").upper()
    return cleaned[:1] if cleaned[:1] in ("A", "B", "C") else ""


def is_meta(sentence: str) -> bool:
    """Frases que no afirman nada verificable: no cuentan ni se retiran."""
    raw = sentence.strip()
    if not raw or raw.endswith("?") or raw.startswith("¿"):
        return True
    if any(raw.startswith(m) or m in raw[:40] for m in _SKIP_MARKS):
        return True
    if _CITATION_LINE.match(raw) and "·" in raw:
        return True
    norm = _norm(raw)
    if any(norm.startswith(o) or o in norm for o in _META_OPENERS):
        return True
    return len(content_terms(raw)) < _MIN_CONTENT_TERMS


# ── Modelo de datos ──────────────────────────────────────────────────────

@dataclass
class ClaimVerdict:
    sentence: str
    verdict: str
    method: str = ""                       # "lexical" | "semantic+lexical" | "judge"
    lexical: float = 0.0
    semantic: Optional[float] = None
    judge: Optional[str] = None            # "A" | "B" | "C" | "UNPARSEABLE" | None
    span: Optional[dict] = None            # {n, locator, sentence}
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"sentence": self.sentence[:200], "verdict": self.verdict,
                "method": self.method, "lexical": round(self.lexical, 3),
                "semantic": None if self.semantic is None else round(self.semantic, 3),
                "judge": self.judge, "span": self.span, "flags": self.flags}


@dataclass
class VerificationReport:
    claims: list[ClaimVerdict] = field(default_factory=list)
    methods: dict = field(default_factory=dict)   # método -> "applied" | "unavailable:…"
    thresholds: dict = field(default_factory=dict)
    evidence_hash: str = ""

    def _by(self, verdict: str) -> list[ClaimVerdict]:
        return [c for c in self.claims if c.verdict == verdict]

    @property
    def supported(self) -> list[ClaimVerdict]:
        return self._by(SUPPORTED)

    @property
    def unsupported(self) -> list[ClaimVerdict]:
        return self._by(UNSUPPORTED)

    @property
    def contradicted(self) -> list[ClaimVerdict]:
        return self._by(CONTRADICTED)

    @property
    def counted(self) -> list[ClaimVerdict]:
        return [c for c in self.claims if c.verdict != META]

    @property
    def supported_ratio(self) -> float:
        n = len(self.counted)
        return (len(self.supported) / n) if n else 1.0

    @property
    def clean(self) -> bool:
        return not self.unsupported and not self.contradicted

    @property
    def state(self) -> str:
        if self.contradicted:
            return "contradicted"
        if not self.counted:
            return "sin_claims"
        if not self.unsupported:
            return "supported"
        if self.supported:
            return "partial"
        return "unsupported"

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "evidence_hash": self.evidence_hash,
            "methods": self.methods,
            "thresholds": self.thresholds,
            "n_claims": len(self.counted),
            "supported": len(self.supported),
            "unsupported": len(self.unsupported),
            "contradicted": len(self.contradicted),
            "meta": len(self._by(META)),
            "supported_ratio": round(self.supported_ratio, 3),
            "claims": [c.to_dict() for c in self.claims][:24],
        }


# ── Verificador ──────────────────────────────────────────────────────────

class ClaimVerifier:
    """Verifica cada claim de una respuesta contra la evidencia congelada.

    `embedder`: callable textos -> vectores (opcional; p. ej. FastEmbedEmbedder).
    `judge`: objeto con `async generate(prompt) -> str` (opcional; LLM soberano).
    """

    def __init__(
        self,
        embedder: Optional[Embedder] = None,
        judge=None,
        *,
        lexical_threshold: float = 0.60,
        semantic_threshold: float = 0.80,
        semantic_min_lexical: float = 0.35,
        contradiction_min_overlap: float = 0.40,
        max_judge_fragments: int = 2,
    ):
        self.embedder = embedder
        self.judge = judge
        self.lexical_threshold = lexical_threshold
        self.semantic_threshold = semantic_threshold
        self.semantic_min_lexical = semantic_min_lexical
        self.contradiction_min_overlap = contradiction_min_overlap
        self.max_judge_fragments = max_judge_fragments
        self.embedder_label = getattr(embedder, "model_id", None) or (
            type(embedder).__name__ if embedder else None)

    # -- evidencia preparada --
    @staticmethod
    def _prepare(freeze: EvidenceFreeze) -> list[dict]:
        prepared = []
        for frag in freeze.fragments:
            text = f"{frag.document}. {frag.text}"
            sentences = split_sentences(frag.text) or [frag.text]
            prepared.append({
                "n": frag.n, "locator": frag.locator, "text": frag.text,
                "terms": set(content_terms(text)),
                "sentences": [(s, set(content_terms(s))) for s in sentences],
            })
        return prepared

    # -- métodos --
    def _lexical(self, claim_terms: list[str], prepared: list[dict]):
        best, best_frag, best_sentence = 0.0, None, ""
        for frag in prepared:
            score = _overlap(claim_terms, frag["terms"])
            if score > best:
                best, best_frag = score, frag
        if best_frag is not None:
            best_sentence = max(
                best_frag["sentences"],
                key=lambda st: _overlap(claim_terms, st[1]))[0]
        return best, best_frag, best_sentence

    def _semantic(self, sentence: str, prepared: list[dict]) -> tuple[Optional[float], Optional[dict], str]:
        if self.embedder is None:
            return None, None, ""
        candidates = [(frag, s) for frag in prepared for s, _ in frag["sentences"]]
        if not candidates:
            return None, None, ""
        vectors = self.embedder([sentence, *[s for _, s in candidates]])
        claim_vec, ev_vecs = vectors[0], vectors[1:]
        best, best_frag, best_sentence = -1.0, None, ""
        for (frag, s), vec in zip(candidates, ev_vecs):
            score = _cosine(claim_vec, vec)
            if score > best:
                best, best_frag, best_sentence = score, frag, s
        return best, best_frag, best_sentence

    @staticmethod
    def judge_prompt(claim: str, fragment: str) -> str:
        # MCQ mínimo: los modelos soberanos afinados (ALIA) siguen el formato
        # test; un ejemplo guiado dentro del prompt los desestabiliza (15-oct).
        return (
            "Pregunta de examen. ¿El FRAGMENTO respalda la AFIRMACIÓN?\n\n"
            f"Afirmación: \"{claim}\"\n\n"
            f"Fragmento: \"{fragment[:1200]}\"\n\n"
            "Elige la opción correcta:\n"
            "A) Sí, el fragmento respalda la afirmación\n"
            "B) No, el fragmento dice lo contrario\n"
            "C) No se puede determinar con este fragmento\n\n"
            "Responde con una sola letra: A, B o C. Nada más.\n"
        )

    async def _judge(self, sentence: str, prepared: list[dict],
                     claim_terms: list[str]) -> tuple[Optional[str], Optional[dict]]:
        """Pregunta al juez sobre los fragmentos más afines. Devuelve la
        letra efectiva y el fragmento que la motivó. A gana; B gana sobre C."""
        ranked = sorted(prepared, key=lambda f: _overlap(claim_terms, f["terms"]),
                        reverse=True)[: self.max_judge_fragments]
        verdict, frag_hit = None, None
        for frag in ranked:
            raw = await self.judge.generate(self.judge_prompt(sentence, frag["text"]))
            letter = _letter(raw) or "UNPARSEABLE"
            if letter == "A":
                return "A", frag
            if letter == "B" and verdict != "A":
                verdict, frag_hit = "B", frag
            elif verdict is None:
                verdict, frag_hit = letter, frag
        return verdict, frag_hit

    # -- veredicto --
    async def verify(self, answer: str, freeze: EvidenceFreeze) -> VerificationReport:
        prepared = self._prepare(freeze)
        report = VerificationReport(
            evidence_hash=freeze.hash,
            thresholds={"lexical": self.lexical_threshold,
                        "semantic": self.semantic_threshold,
                        "semantic_min_lexical": self.semantic_min_lexical,
                        "contradiction_min_overlap": self.contradiction_min_overlap},
            methods={
                "lexical": "applied",
                "semantic": (f"applied:{self.embedder_label}" if self.embedder
                             else "unavailable:NO_EMBEDDER"),
                "judge": ("applied" if self.judge else "unavailable:NOT_CONFIGURED"),
            },
        )
        judge_failed: Optional[str] = None

        for sentence in split_sentences(answer):
            if is_meta(sentence):
                report.claims.append(ClaimVerdict(sentence, META, method="meta"))
                continue
            claim_terms = content_terms(sentence)
            lex, frag, ev_sentence = self._lexical(claim_terms, prepared)
            verdict = ClaimVerdict(sentence, UNSUPPORTED, method="lexical", lexical=lex)
            if frag is not None:
                verdict.span = {"n": frag["n"], "locator": frag["locator"],
                                "sentence": ev_sentence[:240]}

            # Dirección opuesta sobre el mismo desenlace = contradicción (código)
            claim_dir = _direction(sentence)
            ev_dir = _direction(ev_sentence) if ev_sentence else None
            if (claim_dir and ev_dir and claim_dir != ev_dir
                    and lex >= self.contradiction_min_overlap):
                verdict.flags.append("direction_opposite")
            # Polaridad distinta: no se puede dar por respaldado sin juez
            if ev_sentence and (bool(_NEGATION.search(_norm(sentence)))
                                != bool(_NEGATION.search(_norm(ev_sentence)))):
                verdict.flags.append("polarity_mismatch")

            # Semántica (opcional): nunca decide sola
            sem, sem_frag, sem_sentence = self._semantic(sentence, prepared)
            verdict.semantic = sem
            if sem is not None and sem_frag is not None and lex < self.lexical_threshold:
                if verdict.span is None or sem > (self.semantic_threshold + 0.1):
                    verdict.span = {"n": sem_frag["n"], "locator": sem_frag["locator"],
                                    "sentence": sem_sentence[:240]}

            # Juez (opcional, fail-closed)
            if self.judge is not None and judge_failed is None:
                try:
                    letter, jfrag = await self._judge(sentence, prepared, claim_terms)
                    verdict.judge = letter
                    if jfrag is not None and letter in ("A", "B"):
                        verdict.span = {"n": jfrag["n"], "locator": jfrag["locator"],
                                        "sentence": jfrag["text"][:240]}
                except Exception as exc:  # LocalLLMError, transporte…
                    judge_failed = f"unavailable:ERROR:{type(exc).__name__}"
                    report.methods["judge"] = judge_failed

            # Decisión (conservadora; el orden importa):
            #  - B del juez o dirección opuesta por código => CONTRADICTED.
            #  - A del juez => SUPPORTED (el juez lee negación y paráfrasis).
            #  - C o ilegible del juez NO fuerzan nada: se declaran y decide el
            #    código — una coincidencia literal es señal independiente y
            #    más fuerte que un «no lo sé» del modelo.
            if "direction_opposite" in verdict.flags or verdict.judge == "B":
                verdict.verdict, verdict.method = CONTRADICTED, (
                    "judge" if verdict.judge == "B" else "lexical")
            elif verdict.judge == "A":
                verdict.verdict, verdict.method = SUPPORTED, "judge"
            else:
                if verdict.judge in ("C", "UNPARSEABLE"):
                    verdict.flags.append(f"judge_{verdict.judge.lower()}")
                if "polarity_mismatch" in verdict.flags:
                    verdict.verdict = UNSUPPORTED
                elif lex >= self.lexical_threshold:
                    verdict.verdict, verdict.method = SUPPORTED, "lexical"
                elif (sem is not None and sem >= self.semantic_threshold
                      and lex >= self.semantic_min_lexical):
                    verdict.verdict, verdict.method = SUPPORTED, "semantic+lexical"
                else:
                    verdict.verdict = UNSUPPORTED
            report.claims.append(verdict)
        return report


# ── Aplicación del veredicto al texto ────────────────────────────────────

def redact(answer: str, report: VerificationReport) -> tuple[str, int]:
    """Retira las frases UNSUPPORTED dejando marca visible. Devuelve el texto
    y el número de retiradas. Las CONTRADICTED no se retiran aquí: bloquean
    la respuesta completa (decisión del motor)."""
    text, n = answer, 0
    for claim in report.unsupported:
        if claim.sentence in text:
            text = text.replace(claim.sentence, REDACTION_MARK, 1)
            n += 1
    if n:
        text += (f"\n\n⚠️ **Verificación claim↔evidencia**: {n} afirmación(es) "
                 "retirada(s) por falta de respaldo en la evidencia recuperada.")
    return text, n


# ── Benchmark sintético con ground truth (estilo laboratorio OMEGA) ─────

@dataclass
class VerifierCase:
    name: str
    kind: str          # supported_literal | supported_paraphrase | unsupported | contradicted | polarity | meta
    evidence: list[str]
    claim: str
    expected: str      # SUPPORTED | UNSUPPORTED | CONTRADICTED | META


_EV_DM2 = [
    "La metformina es el tratamiento de primera línea en la diabetes tipo 2 y reduce la hemoglobina glucosilada.",
    "La dosis inicial recomendada es de 500 mg cada 12 horas con las comidas, con ajuste progresivo.",
    "Está contraindicada en insuficiencia renal grave por el riesgo de acidosis láctica.",
]


def synthetic_verifier_cases() -> list[VerifierCase]:
    return [
        VerifierCase("literal_1", "supported_literal", _EV_DM2,
                     "La metformina es el tratamiento de primera línea en la diabetes tipo 2.", SUPPORTED),
        VerifierCase("literal_2", "supported_literal", _EV_DM2,
                     "La dosis inicial recomendada es de 500 mg cada 12 horas con las comidas.", SUPPORTED),
        VerifierCase("parafrasis_leve_1", "supported_paraphrase", _EV_DM2,
                     "En la diabetes tipo 2 la metformina se considera tratamiento de primera línea y reduce la hemoglobina glucosilada.", SUPPORTED),
        VerifierCase("parafrasis_leve_2", "supported_paraphrase", _EV_DM2,
                     "Se recomienda iniciar con 500 mg cada 12 horas, ajustando progresivamente la dosis.", SUPPORTED),
        VerifierCase("parafrasis_fuerte_1", "supported_paraphrase", _EV_DM2,
                     "Este fármaco constituye la opción terapéutica inicial preferente en los pacientes diabéticos.", SUPPORTED),
        VerifierCase("parafrasis_fuerte_2", "supported_paraphrase", _EV_DM2,
                     "Debe evitarse cuando el filtrado glomerular está gravemente disminuido.", SUPPORTED),
        VerifierCase("inventado_1", "unsupported", _EV_DM2,
                     "La metformina mejora la función hepática y reduce la esteatosis en todos los pacientes.", UNSUPPORTED),
        VerifierCase("inventado_2", "unsupported", _EV_DM2,
                     "Los ensayos de 2023 demostraron beneficio cardiovascular en prevención primaria.", UNSUPPORTED),
        VerifierCase("inventado_3", "unsupported", _EV_DM2,
                     "La sitagliptina combinada duplica la eficacia glucémica en la primera semana.", UNSUPPORTED),
        VerifierCase("contradice_1", "contradicted", _EV_DM2,
                     "La metformina aumenta la hemoglobina glucosilada en la diabetes tipo 2.", CONTRADICTED),
        VerifierCase("contradice_2", "contradicted",
                     ["El fármaco reduce el riesgo de sangrado frente a placebo en el ensayo aleatorizado."],
                     "El fármaco aumenta el riesgo de sangrado frente a placebo.", CONTRADICTED),
        VerifierCase("polaridad_1", "polarity", _EV_DM2,
                     "La metformina no es el tratamiento de primera línea en la diabetes tipo 2.", UNSUPPORTED),
        VerifierCase("meta_1", "meta", _EV_DM2,
                     "A continuación se resume la evidencia disponible.", META),
        VerifierCase("meta_2", "meta", _EV_DM2,
                     "Lo siento, soy un asistente médico clínico y no puedo responder a consultas no médicas.", META),
    ]


async def run_verifier_benchmark(verifier: Optional[ClaimVerifier] = None) -> dict:
    """Mide el verificador contra ground truth sintético. Métrica de grado
    médico: `fugas` (claims NO respaldados que pasarían como SUPPORTED) debe
    ser 0; `falsos_bloqueos` (respaldados que se retirarían) se MIDE y se
    declara — es el coste del fail-closed, no se oculta."""
    from ..backends.base import EvidenceChunk
    from .grounding import freeze_evidence

    verifier = verifier or ClaimVerifier()
    results, fugas, falsos_bloqueos = [], 0, 0
    for case in synthetic_verifier_cases():
        chunks = [EvidenceChunk(text=t, locator=f"synth_{case.name}_{i}", score=1.0)
                  for i, t in enumerate(case.evidence)]
        report = await verifier.verify(case.claim, freeze_evidence(chunks))
        actual = report.claims[0].verdict if report.claims else META
        ok = actual == case.expected
        leak = case.expected in (UNSUPPORTED, CONTRADICTED) and actual == SUPPORTED
        false_block = case.expected == SUPPORTED and actual in (UNSUPPORTED, CONTRADICTED)
        fugas += leak
        falsos_bloqueos += false_block
        results.append({"case": case.name, "kind": case.kind, "expected": case.expected,
                        "actual": actual, "pass": ok, "leak": leak,
                        "false_block": false_block,
                        "method": report.claims[0].method if report.claims else "",
                        "lexical": round(report.claims[0].lexical, 3) if report.claims else None})
    n_sup = sum(1 for c in synthetic_verifier_cases() if c.expected == SUPPORTED)
    return {
        "methods": verifier and {
            "semantic": "applied" if verifier.embedder else "unavailable",
            "judge": "applied" if verifier.judge else "unavailable"},
        "cases": results,
        "n": len(results),
        "exact": sum(r["pass"] for r in results),
        "fugas": fugas,
        "falsos_bloqueos": falsos_bloqueos,
        "falsos_bloqueos_sobre_respaldados": f"{falsos_bloqueos}/{n_sup}",
    }
