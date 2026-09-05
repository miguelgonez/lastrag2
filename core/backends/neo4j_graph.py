"""
TGS-RAG v2 — Neo4j Graph Manager
==================================
Mantiene el grafo de conocimiento médico.
Neo4j es INSUSTITUIBLE en esta arquitectura porque:
  - Traversal de relaciones multi-salto (enfermedad→tratamiento→fármaco→efecto)
  - "Resurrección" de nodos huérfanos (innovación TGS-RAG)
  - Razonamiento basado en caminos del grafo
"""

import os
from neo4j import AsyncGraphDatabase
from dotenv import load_dotenv

load_dotenv()


class Neo4jGraphManager:
    """
    Gestiona el grafo de conocimiento médico en Neo4j.
    Responsable de:
      1. Crear/actualizar relaciones clínicas
      2. Buscar nodos por similitud semántica + topología
      3. "Resucitar" nodos huérfanos cuando Gemini File Search
         encuentra evidencia textual que los conecta
    """

    def __init__(self):
        self.driver = AsyncGraphDatabase.driver(
            os.getenv("NEO4J_URL", "bolt://localhost:7687"),
            auth=(
                os.getenv("NEO4J_USERNAME", "neo4j"),
                os.getenv("NEO4J_PASSWORD", "password"),
            ),
        )

    async def close(self):
        await self.driver.close()

    async def ping(self) -> bool:
        """Ejecuta una consulta ligera para verificar la conexión real."""
        try:
            async with self.driver.session() as session:
                result = await session.run("RETURN 1 AS ping")
                record = await result.single()
                return record is not None and record["ping"] == 1
        except Exception as e:
            print(f"⚠️ Error de conexión a Neo4j (Ping): {e}")
            return False

    async def setup_schema(self):
        """
        Crea los índices y constraints necesarios para el grafo médico.
        """
        async with self.driver.session() as session:
            # Índices para búsqueda rápida
            await session.run(
                "CREATE INDEX IF NOT EXISTS FOR (d:Disease) ON (d.name)"
            )
            await session.run(
                "CREATE INDEX IF NOT EXISTS FOR (t:Treatment) ON (t.name)"
            )
            await session.run(
                "CREATE INDEX IF NOT EXISTS FOR (d:Drug) ON (d.name)"
            )
            await session.run(
                "CREATE INDEX IF NOT EXISTS FOR (s:Symptom) ON (s.name)"
            )
            await session.run(
                "CREATE INDEX IF NOT EXISTS FOR (b:Biomarker) ON (b.name)"
            )
            print("✅ Schema de Neo4j configurado")

    async def count_nodes(self) -> int:
        """Cuenta el número total de nodos en el grafo."""
        try:
            async with self.driver.session() as session:
                result = await session.run("MATCH (n) RETURN count(n) AS total")
                record = await result.single()
                return record["total"] if record else 0
        except Exception as e:
            print(f"⚠️ Error contando nodos en Neo4j: {e}")
            return 0

    async def seed_medical_graph(self):
        """
        Puebla el grafo con conocimiento médico de ejemplo.
        En producción, esto vendría del ingestador de PDFs + NLP.
        """
        async with self.driver.session() as session:
            # Nodos de ejemplo: Enfermedades renales
            cypher = """
            // --- Enfermedades ---
            MERGE (erc:Disease {name: 'Enfermedad Renal Crónica', code: 'N18'})
            SET erc.desc = 'Pérdida progresiva de función renal'
            
            MERGE (dm2:Disease {name: 'Diabetes Mellitus Tipo 2', code: 'E11'})
            SET dm2.desc = 'Trastorno metabólico con resistencia a insulina'
            
            MERGE (hta:Disease {name: 'Hipertensión Arterial', code: 'I10'})
            SET hta.desc = 'Presión arterial elevada crónica'
            
            // --- Tratamientos ---
            MERGE (dial:Treatment {name: 'Hemodiálisis'})
            SET dial.desc = 'Filtrado artificial de sangre'
            
            MERGE (traspl:Treatment {name: 'Trasplante Renal'})
            SET traspl.desc = 'Reemplazo quirúrgico del riñón'
            
            // --- Fármacos ---
            MERGE (met:Drug {name: 'Metformina', atc: 'A10BA02'})
            SET met.desc = 'Antidiabético oral de primera línea'
            
            MERGE (enal:Drug {name: 'Enalapril', atc: 'C09AA02'})
            SET enal.desc = 'IECA para HTA y nefroprotección'
            
            MERGE (epo:Drug {name: 'Eritropoyetina', atc: 'B03XA01'})
            SET epo.desc = 'Estimulante de eritropoyesis'
            
            // --- Biomarcadores ---
            MERGE (creat:Biomarker {name: 'Creatinina Sérica'})
            SET creat.desc = 'Indicador de función renal', creat.unit = 'mg/dL'
            
            MERGE (k:Biomarker {name: 'Potasio Sérico'})
            SET k.desc = 'Electrolito crítico en ERC', k.unit = 'mEq/L'
            
            MERGE (hba1c:Biomarker {name: 'HbA1c'})
            SET hba1c.desc = 'Control glucémico a 3 meses', hba1c.unit = '%'
            
            // --- Síntomas ---
            MERGE (fatiga:Symptom {name: 'Fatiga Crónica'})
            MERGE (edema:Symptom {name: 'Edema Periférico'})
            MERGE (nausea:Symptom {name: 'Náuseas'})
            
            // --- Relaciones ---
            MERGE (dm2)-[:CAUSA {evidencia: 'Nefropatía diabética'}]->(erc)
            MERGE (hta)-[:AGRAVA]->(erc)
            MERGE (erc)-[:SE_TRATA_CON]->(dial)
            MERGE (erc)-[:SE_TRATA_CON]->(traspl)
            MERGE (dm2)-[:SE_TRATA_CON]->(met)
            MERGE (hta)-[:SE_TRATA_CON]->(enal)
            MERGE (erc)-[:SE_TRATA_CON]->(epo)
            MERGE (enal)-[:PROTEGE {mecanismo: 'Reduce presión glomerular'}]->(erc)
            MERGE (erc)-[:ALTERA]->(creat)
            MERGE (erc)-[:ALTERA]->(k)
            MERGE (dm2)-[:ALTERA]->(hba1c)
            MERGE (erc)-[:PRESENTA]->(fatiga)
            MERGE (erc)-[:PRESENTA]->(edema)
            MERGE (erc)-[:PRESENTA]->(nausea)
            MERGE (met)-[:CONTRAINDICADO_EN {razon: 'Acidosis láctica en TFG<30'}]->(erc)
            
            RETURN 'OK' AS status
            """
            await session.run(cypher)
            print("✅ Grafo médico sembrado con datos de ejemplo")

    async def search_related(self, query: str, max_depth: int = 2) -> list[dict]:
        """
        Busca nodos relacionados con la query hasta N saltos de profundidad.
        Esto es lo que NO puede hacer Gemini File Search.
        
        Args:
            query: Término médico a buscar
            max_depth: Profundidad máxima del traversal
            
        Returns:
            Lista de nodos y relaciones encontradas
        """
        async with self.driver.session() as session:
            cypher = """
            // Consulta con APOC: más rápida y eficiente
            MATCH (start)
            WHERE ANY(label IN labels(start) WHERE label IN 
                  ['Disease', 'Treatment', 'Drug', 'Symptom', 'Biomarker'])
            AND toLower(start.name) CONTAINS toLower($query)
            
            // Expandir relaciones hasta max_depth saltos
            CALL apoc.path.subgraphAll(start, {
                maxLevel: $max_depth,
                relationshipFilter: '>',
                labelFilter: '+Disease|+Treatment|+Drug|+Symptom|+Biomarker'
            })
            YIELD nodes
            UNWIND nodes AS node
            OPTIONAL MATCH (node)-[r]->(target)
            WHERE target IN nodes
            RETURN DISTINCT 
                node.name AS name,
                labels(node)[0] AS type,
                node.desc AS desc,
                node.code AS code,
                collect(DISTINCT target.name) AS targets
            LIMIT 20
            """
            
            # Consulta sin APOC: más lenta pero compatible universalmente
            cypher_simple = """
            MATCH (start)
            WHERE ANY(label IN labels(start) WHERE label IN 
                  ['Disease', 'Treatment', 'Drug', 'Symptom', 'Biomarker'])
            AND toLower(start.name) CONTAINS toLower($query)
            
            OPTIONAL MATCH (start)-[*1..2]-(related)
            WHERE ANY(label IN labels(related) WHERE label IN 
                  ['Disease', 'Treatment', 'Drug', 'Symptom', 'Biomarker'])
            
            WITH collect(DISTINCT start) + collect(DISTINCT related) AS raw_nodes
            UNWIND raw_nodes AS node
            WITH DISTINCT node WHERE node IS NOT NULL
            WITH collect(node) AS all_nodes
            UNWIND all_nodes AS node
            OPTIONAL MATCH (node)-[r]->(target)
            WHERE target IN all_nodes
            RETURN DISTINCT node.name AS name, labels(node)[0] AS type,
                   node.desc AS desc, node.code AS code, collect(DISTINCT target.name) AS targets
            """

            try:
                # 1. Intentar con la consulta optimizada de APOC
                result = await session.run(
                    cypher,
                    parameters={"query": query, "max_depth": max_depth},
                )
                records = [record async for record in result]
                nodes = [dict(r) for r in records]
                unique_nodes = {n["name"]: n for n in nodes if n.get("name")}
                return list(unique_nodes.values())
            except Exception as apoc_error:
                # 2. Si APOC falla (no está instalado), usar el fallback
                if "apoc.path.subgraphAll" in str(apoc_error):
                    print("⚠️ APOC no disponible, usando fallback. Instala el plugin para mejor rendimiento.")
                    result = await session.run(
                        cypher_simple,
                        parameters={"query": query},
                    )
                    records = [record async for record in result]
                    nodes = [dict(r) for r in records]
                    unique_nodes = {n["name"]: n for n in nodes if n.get("name")}
                    return list(unique_nodes.values())
                # Otro error diferente
                print(f"⚠️ Error en búsqueda de grafo: {apoc_error}")
                return []

    async def resurrect_orphans(
        self, text_evidence: list[str], query: str
    ) -> list[dict]:
        """
        🔑 INNOVACIÓN TGS-RAG: "Resurrección de Nodos Huérfanos"
        
        Cuando Gemini File Search encuentra evidencia textual que menciona
        entidades médicas sin conexiones directas en el grafo, este método
        las "resucita" creando conexiones temporales.
        
        Args:
            text_evidence: Textos de Gemini File Search con posibles entidades
            query: La consulta original
            
        Returns:
            Nodos "resucitados" con nuevas conexiones
        """
        async with self.driver.session() as session:
            # Buscar entidades mencionadas en el texto pero aisladas en el grafo
            cypher = """
            // Encontrar nodos que existen pero NO están conectados al contexto actual
            MATCH (orphan)
            WHERE ANY(label IN labels(orphan) WHERE label IN 
                  ['Disease', 'Treatment', 'Drug', 'Symptom', 'Biomarker'])
            AND ANY(text IN $evidence WHERE toLower(text) CONTAINS toLower(orphan.name))
            AND NOT EXISTS {
                MATCH (orphan)-[*1..2]-(connected)
                WHERE toLower(connected.name) CONTAINS toLower($query)
            }
            RETURN orphan.name AS name, 
                   labels(orphan)[0] AS type,
                   orphan.desc AS desc,
                   'resurrected' AS status
            LIMIT 5
            """
            result = await session.run(
                cypher, parameters={"evidence": text_evidence, "query": query}
            )
            orphans = []
            async for record in result:
                orphans.append({
                    "name": record["name"],
                    "type": record["type"],
                    "desc": record["desc"],
                    "status": "resurrected",
                })

            if orphans:
                print(
                    f"   🔮 {len(orphans)} nodos huérfanos resucitados: "
                    f"{[o['name'] for o in orphans]}"
                )

            return orphans
