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
    chunks: list[EvidenceChunk]
    active_graph: list[dict]
    resurrected_nodes: list[dict]
    external_context: str
    response: str
    confidence: float
    is_general_knowledge: bool


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
    ):
        self.backend = backend
        self.lastindex = lastindex
        self.llm = llm
        self.neo4j_graph = neo4j_graph
        self.top_k = top_k
        self.external_search = external_search
        self.app = self._build()

    # --- Nodos ---
    async def _route(self, state: RAGState) -> dict:
        route = route_query(state["query"])
        print(f"🧭 [Hermes] ruta = {route}")
        return {"route": route}

    async def _semantic(self, state: RAGState) -> dict:
        result: RetrievalResult = await self.backend.search(
            state["query"], top_k=self.top_k
        )
        chunks = await self.lastindex.enrich_chunks(result.chunks)
        print(f"🔍 [semantic/{self.backend.name}] {len(chunks)} fragmentos")
        return {"chunks": chunks}

    async def _structural(self, state: RAGState) -> dict:
        chunks = await self.lastindex.structural_search(
            state["query"], top_k=self.top_k
        )
        print(f"📑 [structural] {len(chunks)} bloques con localizacion exacta")
        return {"chunks": chunks}

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

    async def _graph(self, state: RAGState) -> dict:
        all_nodes = await self._graph_nodes(state["query"])
        print(f"🕸️ [graph] {len(all_nodes)} nodos relacionados encontrados")
        return {"active_graph": all_nodes}

    async def _hybrid(self, state: RAGState) -> dict:
        # Triple en paralelo
        sem_task = self.backend.search(state["query"], top_k=self.top_k)
        struct_task = self.lastindex.structural_search(state["query"], top_k=self.top_k)
        graph_task = self._graph_nodes(state["query"])

        sem_res, struct_chunks, active_graph = await asyncio.gather(
            sem_task, struct_task, graph_task
        )
        
        sem_chunks = await self.lastindex.enrich_chunks(sem_res.chunks)
        fused = self._fuse(sem_chunks, struct_chunks)
        print(f"🔀 [hybrid] {len(fused)} fragmentos fusionados, {len(active_graph)} nodos de grafo en contexto")
        return {"chunks": fused, "active_graph": active_graph}

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
            "query": query, "route": "", "chunks": [],
            "active_graph": [], "resurrected_nodes": [],
            "external_context": "", "response": "",
            "confidence": 0.0, "is_general_knowledge": False,
        }
        final = await self.app.ainvoke(initial)
        return {
            "response": final["response"],
            "confidence": final["confidence"],
            "is_general_knowledge": final["is_general_knowledge"],
            "route": final["route"],
            "citations": [
                c.citation.to_dict() for c in final["chunks"] if c.citation
            ],
            "active_graph": final["active_graph"],
            "resurrected_nodes": final["resurrected_nodes"],
            "evidence_count": len(final["chunks"]),
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
