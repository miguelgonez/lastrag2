"""
LastRAG v2 — Motor RAG (agnostico de backend)
=============================================
LangGraph orquesta, pero NUNCA conoce si detras hay Gemini o Qdrant: habla
contra `VectorBackend` y contra `LastIndex`. El router (Hermes) decide la
ruta de recuperacion segun la intencion de la consulta.

Rutas:
  - semantic   : backend vectorial (similitud amplia)
  - structural : LastIndex full-text (localizacion exacta)
  - graph      : grafo clinico Neo4j (relaciones)   [enganche futuro]
  - hybrid     : semantic + structural + fusion
  - external   : fallback PubMed/NICE/Cochrane si no hay evidencia local

Toda respuesta resuelve sus Citations via LastIndex, asi que la trazabilidad
(documento/seccion/pagina) es identica con cualquier backend.

El scoring de confianza es HONESTO: si el modelo admite usar conocimiento
general, la confianza se capa aunque haya evidencia disponible.
"""

from __future__ import annotations

from typing import Any, Optional, TypedDict
import asyncio

from langgraph.graph import StateGraph, START, END

from ..backends.base import VectorBackend, EvidenceChunk, RetrievalResult
from ..lastindex.navigator import LastIndex
from ..llm.base import LLMClient
from ..backends.neo4j_graph import Neo4jGraphManager

# Ola 1-5 (cierre de brecha): capacidades opcionales, defaults = comportamiento
# exacto anterior (cero regresión). Todo lo activo queda declarado en features[].
from .fusion import fuse_rrf, fuse_by_locator
from .iterative import IterativeRouter, SufficiencyGate, decompose_query
from .rerank import ClinicalReranker, CrossEncoderReranker
from .pack import build_pack
from .conflict import ConflictEngine
from .temporal import temporal_filter
from .causal import CausalGate, classify_claim
from .failure_graph import classify_absence, FailureGraph
from .multimodal import boost_multimodal


# ============================================================
# Router (Hermes) — heuristicas explicitas y medibles
# ============================================================

EXACT_HINTS = ("pagina", "página", "seccion", "sección", "donde dice",
               "cita textual", "articulo", "artículo", "apartado", "tabla")
REL_HINTS = ("relacion", "relación", "se trata con", "causa", "interaccion",
             "interacción", "contraindic", "asociado", "conectado")


def route_query(query: str) -> str:
    q = query.lower()
    wants_exact = any(h in q for h in EXACT_HINTS)
    wants_rel = any(h in q for h in REL_HINTS)
    if wants_exact and not wants_rel:
        return "structural"
    if wants_rel and not wants_exact:
        return "graph"
    # Por defecto, hibrido: cubre la mayoria de consultas clinicas.
    return "hybrid"


# ============================================================
# Estado del grafo
# ============================================================

class RAGState(TypedDict):
    query: str
    route: str
    route_effective: str          # ruta EJECUTADA (P0.5: graph->hybrid es visible)
    degradations: list[dict]      # P0.5: todo fallback queda declarado, jamas silencioso
    chunks: list[EvidenceChunk]
    active_graph: list[dict]
    resurrected_nodes: list[dict]
    external_context: str
    response: str
    confidence: float
    is_general_knowledge: bool
    features: dict                # Ola 1-5: fusión/iteración/rerank/pack/causal/...


# ============================================================
# Motor
# ============================================================

class LastRAGEngine:
    def __init__(
        self,
        backend: VectorBackend,
        lastindex: LastIndex,
        llm: LLMClient,
        *,
        neo4j_graph: Optional[Neo4jGraphManager] = None,
        top_k: int = 5,
        external_search=None,  # callable async opcional (PubMed/NICE/Cochrane)
        # ---- Ola 1-5 (cierre de brecha): defaults = comportamiento previo ----
        fusion_mode: str = "locator",      # "locator" (histórico) | "rrf" (Ola 1)
        reranker=None,                     # ClinicalReranker | CrossEncoderReranker
        iterative: bool = False,           # Ola 1: bucle investigador
        max_iterations: int = 3,
        build_pack: bool = False,          # Ola 2: Evidence Pack 2.0 + conflict + causal
        temporal_meta: Optional[dict] = None,  # Ola 2: {locator: {valid_from,...}}
        failure_graph: Optional[FailureGraph] = None,  # Ola 5
    ):
        self.backend = backend
        self.lastindex = lastindex
        self.llm = llm
        self.neo4j_graph = neo4j_graph
        self.top_k = top_k
        self.external_search = external_search
        # Ola 1-5
        self.fusion_mode = fusion_mode
        self.reranker = reranker
        self.iterative = iterative
        self.max_iterations = max_iterations
        self.build_pack = build_pack
        self.temporal_meta = temporal_meta
        self.failure_graph = failure_graph or FailureGraph()
        self._causal_gate = CausalGate()
        self._conflict_engine = ConflictEngine()
        self.app = self._build()

    # --- Nodos ---
    @staticmethod
    def _decl(state: RAGState, entry: dict) -> list[dict]:
        """Adjunta una degradacion al estado (reemplazo completo para LangGraph)."""
        return [*state.get("degradations", []), entry]

    async def _route(self, state: RAGState) -> dict:
        route = route_query(state["query"])
        print(f"🧭 [Hermes] ruta = {route}")
        return {"route": route, "route_effective": route}

    async def _envelope_chunks(self, state: RAGState, chunks: list[EvidenceChunk]) -> tuple[list[EvidenceChunk], list[dict]]:
        """Enriquece citaciones via LastIndex; si Neo4j no responde, la consulta
        continúa PERO la degradación queda declarada (citas sin resolver)."""
        try:
            enriched = await self.lastindex.enrich_chunks(chunks)
            return enriched, []
        except Exception as exc:
            entry = {"component": "lastindex", "reason": f"NEO4J_UNREACHABLE:{type(exc).__name__}",
                     "effect": "citations_unresolved", "fallback": "chunks_sin_cita"}
            return chunks, self._decl(state, entry)

    async def _retrieve_semantic_once(self, query: str) -> tuple[list[EvidenceChunk], list[dict]]:
        result: RetrievalResult = await self.backend.search(query, top_k=self.top_k)
        degradations: list[dict] = []
        if result.degraded_reason:
            degradations.append(
                {"component": f"backend:{self.backend.name}",
                 "reason": result.degraded_reason,
                 "effect": "semantic_retrieval_failed"})
        chunks = result.chunks
        try:
            chunks = await self.lastindex.enrich_chunks(chunks)
        except Exception as exc:
            degradations.append(
                {"component": "lastindex",
                 "reason": f"NEO4J_UNREACHABLE:{type(exc).__name__}",
                 "effect": "citations_unresolved", "fallback": "chunks_sin_cita"})
        return chunks, degradations

    async def _run_iterative(self, query: str, retrieve_once, degradations: list[dict]):
        """Ola 1: bucle investigador sobre cualquier vía de recuperación."""
        router = IterativeRouter(max_iterations=self.max_iterations)

        async def retrieve(q: str, top_k: int) -> list[EvidenceChunk]:
            chunks, decls = await retrieve_once(q)
            degradations.extend(decls)
            return chunks

        return await router.run(query, retrieve, top_k=self.top_k)

    def _postprocess(self, state: RAGState, chunks: list[EvidenceChunk]) -> tuple[list[EvidenceChunk], dict]:
        """Ola 1-3, post-recuperación: temporal → rerank → boost multimodal.
        Cada paso queda declarado en features (jamás silencioso)."""
        feats: dict = {}
        chunks = list(chunks)
        if self.temporal_meta is not None:
            dec = temporal_filter(chunks, self.temporal_meta, state["query"])
            feats["temporal"] = {"mode": dec.mode, "dropped": dec.dropped,
                                 "undated_kept": dec.undated_kept}
            chunks = dec.kept
        if self.reranker is not None:
            rr = self.reranker.rerank(state["query"], chunks)
            chunks = rr.ranked
            feats["rerank"] = {"model": rr.model, "reasons": rr.reasons}
        chunks, mm = boost_multimodal(chunks, state["query"])
        feats["multimodal_boost"] = mm
        return chunks, feats

    async def _semantic(self, state: RAGState) -> dict:
        degradations = list(state.get("degradations", []))
        feats = dict(state.get("features") or {})
        if self.iterative:
            chunks, iterations, iter_degr = await self._run_iterative(
                state["query"], self._retrieve_semantic_once, degradations)
            feats["iterations"] = iterations
            if iter_degr:
                degradations.append(iter_degr)
        else:
            chunks, decls = await self._retrieve_semantic_once(state["query"])
            degradations.extend(decls)
        chunks, pp = self._postprocess(state, chunks)
        feats.update(pp)
        print(f"🔍 [semantic/{self.backend.name}] {len(chunks)} fragmentos")
        return {"chunks": chunks, "degradations": degradations, "features": feats}

    async def _structural(self, state: RAGState) -> dict:
        degradations = list(state.get("degradations", []))
        feats = dict(state.get("features") or {})

        async def once(query: str):
            try:
                return await self.lastindex.structural_search(query, top_k=self.top_k), []
            except Exception as exc:
                entry = {"component": "lastindex",
                         "reason": f"NEO4J_UNREACHABLE:{type(exc).__name__}",
                         "effect": "structural_retrieval_failed",
                         "fallback": "sin_fragmentos"}
                return [], [entry]

        if self.iterative:
            chunks, iterations, iter_degr = await self._run_iterative(
                state["query"], once, degradations)
            feats["iterations"] = iterations
            if iter_degr:
                degradations.append(iter_degr)
        else:
            chunks, decls = await once(state["query"])
            degradations.extend(decls)
        chunks, pp = self._postprocess(state, chunks)
        feats.update(pp)
        if not chunks and any(d.get("effect") == "structural_retrieval_failed"
                              for d in degradations):
            print(f"⚠️ [structural] degradado")
        print(f"📑 [structural] {len(chunks)} bloques con localizacion exacta")
        return {"chunks": chunks, "degradations": degradations, "features": feats}

    async def _graph_nodes(self, query: str) -> list[dict]:
        if not self.neo4j_graph:
            return []

        stopwords = {"que", "como", "cual", "cuales", "son", "los", "las", "del", "de", "la", "el", "en", "con", "por", "para", "una", "un", "se", "es", "y", "o", "a", "al"}
        words = query.lower().replace("?", "").replace("¿", "").split()
        terms = [w for w in words if len(w) > 3 and w not in stopwords][:5]

        all_nodes = []
        seen_nodes = {}
        for term in terms:
            nodes = await self.neo4j_graph.search_related(query=term, max_depth=2)
            for n in nodes:
                name = n.get("name")
                if not name: continue
                if name not in seen_nodes:
                    seen_nodes[name] = n
                    all_nodes.append(n)
                else:
                    existing_targets = set(seen_nodes[name].get("targets", []))
                    existing_targets.update(n.get("targets", []))
                    seen_nodes[name]["targets"] = list(existing_targets)

        return all_nodes

    async def _graph_nodes_safe(self, query: str) -> tuple[list[dict], dict | None]:
        """Devuelve (nodos, degradacion_o_None). Un fallo de Neo4j nunca se
        traga: se devuelve como degradacion y el llamador la declara."""
        if not self.neo4j_graph:
            return [], {"component": "neo4j_graph", "reason": "NOT_CONFIGURED",
                        "effect": "graph_context_unavailable"}
        try:
            return await self._graph_nodes(query), None
        except Exception as exc:
            return [], {"component": "neo4j_graph",
                        "reason": f"NEO4J_ERROR:{type(exc).__name__}",
                        "effect": "graph_context_unavailable"}

    async def _graph(self, state: RAGState) -> dict:
        # P0.5: si el grafo no esta disponible, la consulta NO sigue el camino
        # graph en silencio: se ejecuta hybrid y la degradacion queda declarada
        # en la respuesta (route_effective + degradations).
        nodes, degradation = await self._graph_nodes_safe(state["query"])
        if degradation:
            hybrid_update = await self._hybrid(state)
            entry = {**degradation, "from_route": "graph", "to_route": "hybrid",
                     "fallback": "hybrid_retrieval"}
            hybrid_update["degradations"] = self._decl(
                {**state, "degradations": hybrid_update.get("degradations",
                                                            state.get("degradations", []))},
                entry,
            )
            print(f"⚠️ [graph] DEGRADADO a hybrid: {degradation['reason']}")
            return {**hybrid_update, "route_effective": "hybrid"}
        print(f"🕸️ [graph] {len(nodes)} nodos relacionados encontrados")
        return {"active_graph": nodes}

    async def _retrieve_hybrid_once(self, query: str) -> tuple[list[EvidenceChunk], list[dict], list[dict]]:
        """Una pasada del triple (semantic+structural+graph) con fusión según
        `fusion_mode`. Cada fuente declara su propia degradación."""
        sem_res, struct, graph = await asyncio.gather(
            self.backend.search(query, top_k=self.top_k),
            self._structural_search_safe(query),
            self._graph_nodes_safe(query),
        )
        degradations: list[dict] = []
        if sem_res.degraded_reason:
            degradations.append({"component": f"backend:{self.backend.name}",
                                 "reason": sem_res.degraded_reason,
                                 "effect": "semantic_retrieval_failed"})
        if struct[1]:
            degradations.append({**struct[1], "effect": "structural_retrieval_failed"})
        if graph[1]:
            degradations.append(graph[1])

        sem_chunks = sem_res.chunks
        try:
            sem_chunks = await self.lastindex.enrich_chunks(sem_chunks)
        except Exception as exc:
            degradations.append({"component": "lastindex",
                                 "reason": f"NEO4J_UNREACHABLE:{type(exc).__name__}",
                                 "effect": "citations_unresolved",
                                 "fallback": "chunks_sin_cita"})

        if self.fusion_mode == "rrf":
            fused = fuse_rrf([sem_chunks, struct[0]])
        else:
            fused = fuse_by_locator(struct[0], sem_chunks)
        return fused, degradations, graph[0]

    async def _hybrid(self, state: RAGState) -> dict:
        # Triple en paralelo; cada fuente declara su propia degradacion
        degradations = list(state.get("degradations", []))
        feats = dict(state.get("features") or {})
        feats["fusion_mode"] = self.fusion_mode
        graph_nodes: list[dict] = []

        async def once(query: str):
            chunks, decls, gnodes = await self._retrieve_hybrid_once(query)
            degradations.extend(decls)
            graph_nodes.extend(gnodes)
            return chunks, []

        if self.iterative:
            chunks, iterations, iter_degr = await self._run_iterative(
                state["query"], once, degradations)
            feats["iterations"] = iterations
            if iter_degr:
                degradations.append(iter_degr)
        else:
            chunks, _ = await once(state["query"])

        chunks, pp = self._postprocess(state, chunks)
        feats.update(pp)
        print(f"🔀 [hybrid/{self.fusion_mode}] {len(chunks)} fragmentos fusionados, "
              f"{len(graph_nodes)} nodos de grafo en contexto")
        return {"chunks": chunks, "active_graph": graph_nodes,
                "degradations": degradations, "features": feats}

    async def _structural_search_safe(self, query: str) -> tuple[list[EvidenceChunk], dict | None]:
        try:
            return await self.lastindex.structural_search(query, top_k=self.top_k), None
        except Exception as exc:
            return [], {"component": "lastindex",
                        "reason": f"NEO4J_UNREACHABLE:{type(exc).__name__}"}

    async def _external(self, state: RAGState) -> dict:
        if not self.external_search:
            return {"external_context": ""}
        try:
            data = await self.external_search(state["query"], max_results=3)
            lines = []
            for src in ("pubmed", "nice", "cochrane"):
                for item in data.get(src, []):
                    lines.append(
                        f"- {src.upper()} ({item.get('year','N/A')}): {item.get('title','')}"
                    )
            return {"external_context": "\n".join(lines)}
        except Exception as e:
            print(f"⚠️ external: {e}")
            return {"external_context": ""}

    async def _grade(self, state: RAGState) -> dict:
        chunks = state.get("chunks", [])
        if not chunks:
            return {"chunks": []}
            
        # Combina los textos y pide al LLM evaluar si la evidencia responde a la consulta y es del dominio correcto.
        texts = "\n---\n".join([f"Fragmento {i+1}:\n{c.text[:600]}" for i, c in enumerate(chunks)])
        query = state["query"]
        
        prompt = f"""
        Actúa como un evaluador estricto. Revisa si los siguientes fragmentos de texto contienen información relevante para responder a la consulta médica del usuario.
        
        Consulta del usuario: "{query}"
        
        Fragmentos recuperados:
        {texts}
        
        Reglas de evaluación:
        1. Si la consulta del usuario NO tiene relación alguna con medicina, salud, biología clínica o pacientes (por ejemplo, si pregunta sobre urbanismo, leyes de construcción, recetas de cocina, etc.), debes responder "IRRELEVANTE" inmediatamente.
        2. Si los fragmentos recuperados NO contienen información médica, clínica o científica (por ejemplo, son sentencias judiciales sobre urbanismo), debes responder "IRRELEVANTE".
        3. Responde "RELEVANTE" ÚNICAMENTE si la consulta es de índole médica Y al menos uno de los fragmentos contiene información clínica que ayude a responderla.
        
        Tu respuesta debe ser una sola palabra: RELEVANTE o IRRELEVANTE.
        """
        
        # Llama al LLM para calificar (temperature 0 es ideal, pero ya está configurado en el backend/cliente)
        decision = await self.llm.generate(prompt)
        
        if "IRRELEVANTE" in decision.upper():
            print(f"🚫 [grade] Se descartaron {len(chunks)} fragmentos por irrelevancia de dominio.")
            return {"chunks": []}
        else:
            print(f"✅ [grade] Evidencia validada para la consulta.")
            return {"chunks": chunks}

    async def _generate(self, state: RAGState) -> dict:
        chunks = state.get("chunks", [])
        active_graph = state.get("active_graph", [])
        external = state.get("external_context", "")
        feats = dict(state.get("features") or {})

        pack_render = None
        if self.build_pack and chunks:
            # Ola 2/4: la unidad central es la relación claim↔evidence.
            gaps = []
            for it in feats.get("iterations", []):
                gaps.extend(it.get("gaps", []))
            causal_levels = {
                c.locator: classify_claim(c.text) for c in chunks
            }
            pack = build_pack(state["query"], chunks, gaps=gaps,
                              causal_levels={
                  loc: lvl for loc, lvl in causal_levels.items() if lvl})
            conflicts = self._conflict_engine.detect(pack.claims)
            pack.contradictions = conflicts
            feats["pack"] = {"claims": len(pack.claims),
                             "conflicts": self._conflict_engine.summarize(conflicts),
                             "gaps": pack.gaps}
            pack_render = pack.render_for_prompt()

            # Ola 4: frontera correlación→recomendación (código, no prosa)
            verdict = self._causal_gate.check(state["query"], pack.claims)
            feats["causal_gate"] = verdict.to_dict()
            if not verdict.allowed:
                abstention = (
                    f"⛔ **Abstención causal (fail-closed).** {verdict.reason}. "
                    f"\n\n{verdict.abstention}"
                )
                print(f"⛔ [causal-gate] abstención: {verdict.reason}")
                if self.failure_graph:
                    self.failure_graph.record(
                        "UNSUPPORTED_GENERATION",
                        detail=f"causal_gate bloqueó recomendación "
                               f"(best={verdict.best_level})")
                return {"response": abstention, "confidence": 0.05,
                        "is_general_knowledge": False, "features": feats}

        if pack_render is not None:
            # El LLM recibe el OBJETO estructurado, no la nube de chunks.
            evidence = pack_render
        else:
            evidence = "\n---\n".join(c.text for c in chunks[: self.top_k])
        citations = "\n".join(
            f"- {c.citation.short()}" for c in chunks if c.citation
        )

        graph_context = ""
        if active_graph:
            graph_context = "\n".join(f"- [{n.get('type', '?')}] {n.get('name', '?')}: {n.get('desc', 'Sin descripción')}" for n in active_graph)

        prompt = self._prompt(state["query"], evidence, citations, external, graph_context)
        text = await self.llm.generate(prompt)

        confidence, is_general = self._score(text, chunks, external)
        print(f"🧠 [generate] conf={confidence:.0%} general={is_general}")
        return {
            "response": text,
            "confidence": confidence,
            "is_general_knowledge": is_general,
            "features": feats,
        }

    # --- Construccion del grafo ---
    def _build(self):
        wf = StateGraph(RAGState)
        wf.add_node("route", self._route)
        wf.add_node("semantic", self._semantic)
        wf.add_node("structural", self._structural)
        wf.add_node("graph", self._graph)
        wf.add_node("hybrid", self._hybrid)
        wf.add_node("grade", self._grade)
        wf.add_node("external", self._external)
        wf.add_node("generate", self._generate)

        wf.add_edge(START, "route")
        wf.add_conditional_edges(
            "route",
            lambda s: s["route"],
            {
                "semantic": "semantic",
                "structural": "structural",
                "hybrid": "hybrid",
                "graph": "graph",
            },
        )
        
        # Las rutas de recuperación envían sus resultados al nodo de evaluación (grade)
        for node in ("semantic", "structural", "hybrid", "graph"):
            wf.add_edge(node, "grade")
            
        # Tras evaluar, si no hay evidencia -> external; si hay -> generate
        wf.add_conditional_edges(
            "grade",
            self._needs_external,
            {"external": "external", "generate": "generate"},
        )
        wf.add_edge("external", "generate")
        wf.add_edge("generate", END)
        return wf.compile()

    @staticmethod
    def _needs_external(state: RAGState) -> str:
        # Se necesita fallback si no hay chunks ni nodos de grafo
        if not state.get("chunks") and not state.get("active_graph"):
            return "external"
        return "generate"

    async def run(self, query: str) -> dict[str, Any]:
        initial: RAGState = {
            "query": query, "route": "", "route_effective": "", "degradations": [],
            "chunks": [], "active_graph": [], "resurrected_nodes": [],
            "external_context": "", "response": "",
            "confidence": 0.0, "is_general_knowledge": False, "features": {},
        }
        final = await self.app.ainvoke(initial)
        features = final.get("features") or {}
        chunks = final["chunks"]
        # Ola 5: taxonomía de la ausencia — NO_EVIDENCE vs INSUFFICIENT_
        # EVIDENCE son distinguibles en la respuesta (remedio distinto).
        coverage = None
        iters = features.get("iterations") or []
        if iters:
            coverage = iters[-1].get("coverage")
        absence = classify_absence(
            len(chunks), coverage,
            claims_count=features.get("pack", {}).get("claims", 0))
        if not chunks and self.failure_graph:
            self.failure_graph.record(
                "RETRIEVAL_MISS",
                detail=f"0 fragmentos tras pipeline (ruta={final.get('route')})")
        return {
            "response": final["response"],
            "confidence": final["confidence"],
            "is_general_knowledge": final["is_general_knowledge"],
            "route": final["route"],
            "route_effective": final.get("route_effective") or final["route"],
            "degradations": final.get("degradations", []),
            "citations": [
                c.citation.to_dict() for c in chunks if c.citation
            ],
            "evidence": [c.to_dict() for c in chunks],
            "active_graph": final["active_graph"],
            "resurrected_nodes": final["resurrected_nodes"],
            "evidence_count": len(chunks),
            # Ola 1-5
            "features": features,
            "absence": absence,
        }

    # --- helpers ---
    @staticmethod
    def _fuse(
        a: list[EvidenceChunk], b: list[EvidenceChunk]
    ) -> list[EvidenceChunk]:
        """Fusion por locator; el estructural (citacion exacta) tiene prioridad."""
        by_loc: dict[str, EvidenceChunk] = {}
        for c in b:  # estructural primero (citacion confiable)
            by_loc[c.locator or c.text[:40]] = c
        for c in a:
            key = c.locator or c.text[:40]
            if key not in by_loc:
                by_loc[key] = c
        return list(by_loc.values())

    @staticmethod
    def _prompt(query: str, evidence: str, citations: str, external: str, graph_context: str) -> str:
        return f"""Eres un asistente medico experto. Responde la consulta usando
la evidencia proporcionada. Procesa evidencia en cualquier idioma y responde
en el idioma de la consulta.

## Consulta
{query}

## Evidencia del Grafo de Conocimiento (Neo4j)
{graph_context or 'No se encontraron relaciones en el grafo.'}

## Evidencia (documentos indexados)
{evidence or 'Sin evidencia textual (descartada por irrelevancia o no encontrada).'}

## Citaciones disponibles
{citations or 'Sin citaciones.'}

## Evidencia externa (fallback)
{external or 'No se requirio.'}

## Instrucciones
1. Responde de forma completa y estructurada.
2. CITA usando exclusivamente las citaciones proporcionadas.
3. Si la consulta NO tiene ninguna relación con medicina o salud clínica (por ejemplo, urbanismo, leyes, recetas de cocina, etc.) y la evidencia es nula, DEBES RECHAZAR la consulta respondiendo EXACTAMENTE: "Lo siento, soy un asistente médico clínico. Mi base de datos y conocimientos están restringidos estrictamente al ámbito de la salud. No puedo responder a consultas sobre temas no médicos." No añadas nada más.
4. Si la consulta SÍ es médica, pero la evidencia proporcionada es insuficiente o nula, responde a la consulta utilizando tu conocimiento médico general, iniciando tu respuesta EXACTAMENTE con: "⚠️ **Aviso:** No se encontró evidencia en los documentos indexados. Esta respuesta se basa en conocimiento médico general."
5. NUNCA inventes información médica. Cíñete ESTRICTAMENTE a la evidencia proporcionada cuando esté disponible.
"""

    @staticmethod
    def _score(
        text: str, chunks: list[EvidenceChunk], external: str
    ) -> tuple[float, bool]:
        """Scoring honesto: distingue evidencia disponible de evidencia usada."""
        n = len(chunks)
        has_external = bool(external)
        admitted_general = (
            "⚠️ **Aviso:**" in text
            or "conocimiento médico general" in text.lower()
            or "soy un asistente médico clínico" in text.lower()
        )
        if admitted_general:
            return (0.10), True
        if n == 0 and not has_external:
            return 0.15, True
        # Confianza ponderada por nº de fragmentos con citacion exacta
        cited = sum(1 for c in chunks if c.citation and c.citation.page is not None)
        score = cited * 1.5 + n * 0.8 + (3 if has_external else 0)
        return min(1.0, score / 10.0), False
