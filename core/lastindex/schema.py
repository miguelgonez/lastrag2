"""
LastRAG v2 — LastIndex: Esquema del Arbol Documental
====================================================
PageIndex propio. Persiste la estructura jerarquica de cada documento en
Neo4j para que la CITACION sea identica venga de Gemini o de Qdrant.

Jerarquia:
    (Document)-[:HAS_CHAPTER]->(Chapter)
    (Chapter)-[:HAS_SECTION]->(Section)
    (Section)-[:HAS_SECTION]->(Section)      // recursivo (subsecciones)
    (Section)-[:HAS_BLOCK]->(EvidenceBlock)
    (EvidenceBlock)-[:ON_PAGE]->(Page)
    (EvidenceBlock)-[:MENTIONS]->(Concept)    // puente con el grafo clinico

Cada EvidenceBlock guarda:
    - block_id        : id estable (= locator que devuelve el backend vectorial)
    - text            : texto del bloque
    - page            : pagina exacta
    - section_path    : ruta legible "Cap 3 > 3.2 > Dosificacion"
    - order           : orden dentro de la seccion

El `block_id` es la clave que une los dos mundos: el backend vectorial indexa
el mismo texto con block_id como locator; LastIndex resuelve block_id -> Citation.
"""

from __future__ import annotations

# Constraints e indices. Idempotentes (IF NOT EXISTS).
SCHEMA_STATEMENTS: list[str] = [
    # Unicidad de nodos clave
    "CREATE CONSTRAINT doc_id IF NOT EXISTS "
    "FOR (d:Document) REQUIRE d.document_id IS UNIQUE",

    "CREATE CONSTRAINT block_id IF NOT EXISTS "
    "FOR (b:EvidenceBlock) REQUIRE b.block_id IS UNIQUE",

    "CREATE CONSTRAINT concept_name IF NOT EXISTS "
    "FOR (c:Concept) REQUIRE c.name IS UNIQUE",

    # Indices para busqueda estructural
    "CREATE INDEX block_page IF NOT EXISTS "
    "FOR (b:EvidenceBlock) ON (b.page)",

    "CREATE INDEX section_title IF NOT EXISTS "
    "FOR (s:Section) ON (s.title)",

    # Full-text sobre el texto de los bloques (modo estructural por palabras)
    "CREATE FULLTEXT INDEX block_fulltext IF NOT EXISTS "
    "FOR (b:EvidenceBlock) ON EACH [b.text, b.section_path]",
]


# Cypher para upsert de un documento completo a partir de su arbol.
# Se ejecuta por bloque para mantener la idempotencia y la procedencia.
UPSERT_DOCUMENT = """
MERGE (d:Document {document_id: $document_id})
  SET d.title = $title,
      d.source_path = $source_path,
      d.specialty = $specialty,
      d.doc_type = $doc_type,
      d.updated_at = datetime()
"""

UPSERT_BLOCK = """
MATCH (d:Document {document_id: $document_id})

// Capitulo (puede ser null -> seccion cuelga directa del documento)
FOREACH (_ IN CASE WHEN $chapter IS NULL THEN [] ELSE [1] END |
  MERGE (ch:Chapter {document_id: $document_id, title: $chapter})
  MERGE (d)-[:HAS_CHAPTER]->(ch)
)

// Seccion (ruta canonica). Usamos section_path como clave estable.
MERGE (s:Section {document_id: $document_id, path: $section_path})
  SET s.title = $section_title
WITH d, s

// Enganchar seccion al capitulo o al documento
FOREACH (_ IN CASE WHEN $chapter IS NULL THEN [1] ELSE [] END |
  MERGE (d)-[:HAS_SECTION]->(s)
)
FOREACH (_ IN CASE WHEN $chapter IS NULL THEN [] ELSE [1] END |
  MERGE (ch:Chapter {document_id: $document_id, title: $chapter})
  MERGE (ch)-[:HAS_SECTION]->(s)
)

// Bloque de evidencia
MERGE (b:EvidenceBlock {block_id: $block_id})
  SET b.text = $text,
      b.page = $page,
      b.section_path = $section_path,
      b.order = $order,
      b.document_id = $document_id
MERGE (s)-[:HAS_BLOCK]->(b)

// Pagina
MERGE (p:Page {document_id: $document_id, number: $page})
MERGE (b)-[:ON_PAGE]->(p)
"""


# Resolucion locator (block_id) -> Citation completa.
# Es el corazon de la paridad de citacion entre backends.
RESOLVE_CITATION = """
MATCH (b:EvidenceBlock {block_id: $block_id})
OPTIONAL MATCH (d:Document {document_id: b.document_id})
// El capitulo se busca SIEMPRE dentro del mismo documento: `path` solo es
// unico por (document_id, path). Sin esta restriccion, dos documentos con la
// misma ruta de seccion ("1. Introduccion") podian atribuir el capitulo del
// documento equivocado a la cita.
OPTIONAL MATCH (ch:Chapter {document_id: b.document_id})-[:HAS_SECTION*0..]->
               (:Section {document_id: b.document_id, path: b.section_path})
RETURN
  coalesce(d.title, b.document_id) AS document,
  b.document_id                   AS document_id,
  ch.title                        AS chapter,
  b.section_path                  AS section,
  b.page                          AS page,
  b.block_id                      AS block_id
LIMIT 1
"""


# Retriever ESTRUCTURAL puro: dada una consulta por palabras clave,
# devuelve bloques con su localizacion exacta (sin pasar por vectores).
# Modo "localizacion exacta" del roadmap.
STRUCTURAL_SEARCH = """
CALL db.index.fulltext.queryNodes('block_fulltext', $lucene_query)
YIELD node AS b, score
OPTIONAL MATCH (d:Document {document_id: b.document_id})
RETURN
  b.block_id      AS block_id,
  b.document_id   AS document_id,
  b.text          AS text,
  b.page          AS page,
  b.section_path  AS section,
  d.title         AS document,
  score
ORDER BY score DESC
LIMIT $top_k
"""
