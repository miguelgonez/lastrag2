# Proceso de comprobación de retractaciones — corpus PubMed (piloto y escalas)

**Para:** curación del corpus (la capa 5 lee el resultado; nunca lo consulta ella).
**Regla que sirve:** «un paper validado por pares y que **a la fecha** no haya sido refutado» (PI, 22-oct). «A la fecha» exige fuente + periodicidad + `retraction_checked_at` estampado; la capa 5 (`core/rag/provenance.py`) rechaza comprobaciones sin fecha o con más de `max_check_age_days` (180 por defecto).

## Decisión recomendada

**Fuente primaria: PubMed (E-utilities).** El corpus del piloto ES PubMed (48.399 abstracts), y PubMed marca la retractación directamente sobre el artículo:

- `PublicationType "Retracted Publication"` — **35.203 artículos** con esa marca (contado vía `esearch` el 2026-10-23).
- `PublicationType "Expression of Concern"` — **4.050 artículos** (idem).
- Verificado en vivo: PMID 9500320 (Wakefield 1998, Lancet) devuelve `<PublicationType UI="D016441">Retracted Publication</PublicationType>` en su XML de `efetch`.
- Llamada de trabajo: `efetch.fcgi?db=pubmed&id=<PMIDs separados por coma>&rettype=abstract&retmode=xml` — lotes de 200 PMIDs por llamada; sin clave API ~3 req/s (48.399 PMIDs ≈ 242 llamadas ≈ 2-3 minutos). Con clave E-utilities (gratuita) el lote es mayor y el rate sube.

**Fuente secundaria (cribado cruzado): Retraction Watch Database (Crossref).** CSV completo, CC0:

- `https://gitlab.com/crossref/retraction-watch-data/-/raw/main/retraction_watch.csv` — **HTTP 200, 68 MB, verificado 2026-10-23**. Actualizado cada día laborable; >67.000 retractaciones. Crossref la mantiene desde sep-2023; la descarga directa del GitLab es la vía recomendada por el propio Crossref.
- Rol: capturar retractaciones anunciadas por el editor aún no indexadas como tal en PubMed, y enriquecer con `Reason`/`RetractionNature`. Matching por **DOI** (y título normalizado como respaldo), nunca por autor.

**Regla de fusión (recomendada, decisión final del curador):** retractado o expresión de preocupación en **cualquiera** de las dos fuentes → `retraction_status` = `retracted` / `concern` respectivamente (ambos bloqueantes en capa 5); en ninguna → `none`. Las discrepancias se anotan en `note`, no se promedian: si RW lista una retractación que PubMed no marca, el hecho es la retractación (anuncio del editor), no la indexación.

## Periodicidad recomendada

1. **Al ingerir** (cada ola/refresh del corpus): el artículo nuevo entra ya etiquetado — sin comprobación no es afirmable.
2. **Barrido completo cada 90 días** sobre todo el corpus: la mitad del `max_check_age_days=180` del motor, de modo que ninguna fuente cualificada pueda caducar (quedar >180 días) sin haber pasado por un barrido. 48.399 PMIDs ≈ 3 min de E-utilities + un cruce local contra el CSV de RW.
3. Cada pasada re-estampa `retraction_checked_at` = fecha ISO de la comprobación (UTC), aunque el estado no cambie: la vigencia es del chequeo, no del hallazgo.

**Adiciones del arquitecto (23-oct, aprobadas):**

4. **Un hallazgo de retractación es un EVENTO, no espera al barrido**: en cuanto una fuente (vía alerta, ingestión nueva o cruce RW) aparezca retractada o con expresión de preocupación, se re-estampa inmediatamente su `retraction_status` y los documentos afectados quedan bloqueados (la capa 5 ya los retiene por contrato) — sin esperar al ciclo de 90 días.
5. **Cada estampado registra FUENTE y FECHA por documento** (`retraction_source`: `pubmed` | `rwdb` | `pubmed+rwdb`), que es el contrato de trazabilidad de la capa 5. La discrepancia entre fuentes se anota en `note`, no se promedia.

## Estado que deja la curación (contrato con capa 5)

```json
{
  "tier": "peer_reviewed",
  "retraction_status": "none" | "retracted" | "concern" | "unknown",
  "retraction_checked_at": "2026-10-23",
  "retraction_source": "pubmed" | "rwdb" | "pubmed+rwdb",
  "identifier": "<PMID o DOI>",
  "note": "opcional: discrepancia RW/PubMed, motivo de RW, etc."
}
```

`unknown` solo mientras la primera pasada no cubre el documento: una fuente sin comprobar NO es afirmable (`UNKNOWN != PASS`).

## Coste y evidencia de este documento

- Conteos y respuesta XML de PubMed: consultas `esearch`/`efetch` reales ejecutadas el **2026-10-23**.
- CSV de Retraction Watch: `curl -I` HTTP 200 con `content-length: 68.068.181` el **2026-10-23**.
- Nada de lo anterior acredita calidad de la curación: la acreditación la da la pasada ejecutada con sus recibos (fichero de salida con fecha, conteos por estado y nº de discrepancias RW/PubMed).
