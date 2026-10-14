#!/usr/bin/env python3
"""
Fase 0 — Descarga controlada del piloto PubMed (NO todo PubMed)
================================================================
4 temas × N abstracts (5 años, con abstract) vía NCBI E-utilities
(esearch → efetch XML), sin clave (≤3 req/s con pausas). Salida:
  cierre_brecha_real/data/pubmed_pilot.parquet (+ .jsonl)
Esquema: pmid, title, abstract, pub_date, mesh_terms, doi, language, topic.
La etiqueta `topic` es el silver-gold del sourcing (declarado en prereg).
Fase 1 (Apache Spark/Delta) queda para el host Spark; este fichero es el
parquet de validación previa que ese plan exige.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "cierre_brecha_real" / "data"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

TOPICS = {
    "sglt2": '("sodium-glucose transporter 2 inhibitors"[MeSH Terms] OR sglt2[Title/Abstract])',
    "metformin": '(metformin[MeSH Terms] AND diabetes[Title/Abstract])',
    "heart_failure": '("heart failure"[MeSH Terms] AND (therapy[MeSH Subheading] OR treatment[Title/Abstract]))',
    "lung_screening": '("lung neoplasms"[MeSH Terms] AND (screening[Title/Abstract] OR "early detection"[Title/Abstract]))',
}
PER_TOPIC = 300
BATCH = 200
UA = {"User-Agent": "lastrag2-pilot/1.0 (research; contact: repo maintainer)"}


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def esearch(term: str, n: int) -> list[str]:
    q = urllib.parse.urlencode({
        "db": "pubmed", "term": term, "retmax": n,
        "retmode": "json", "datetype": "pdat", "reldate": 1825,  # 5 años
        "sort": "relevance",
    })
    data = json.loads(get(f"{EUTILS}/esearch.fcgi?{q}"))
    return [str(p) for p in data["esearchresult"].get("idlist", [])]


def efetch(pmids: list[str]) -> bytes:
    q = urllib.parse.urlencode({"db": "pubmed", "retmode": "xml",
                                "id": ",".join(pmids)})
    return get(f"{EUTILS}/efetch.fcgi?{q}")


def parse_articles(xml_bytes: bytes, topic: str) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    out = []
    for art in root.iter("PubmedArticle"):
        pmid_el = art.find(".//PubmedData/ArticleIdList/ArticleId[@IdType='pubmed']")
        med = art.find(".//MedlineCitation")
        article = med.find("Article") if med is not None else None
        if pmid_el is None or article is None:
            continue
        title = "".join(article.findtext("ArticleTitle", default="") or "")
        abstr = article.find("Abstract")
        text = " ".join("".join(at.itertext()).strip()
                        for at in (abstr.findall("AbstractText") if abstr is not None else []))
        if not title or len(text) < 200:  # exige abstract sustancial
            continue
        year = (article.findtext(".//PubDate/Year")
                or article.findtext(".//PubDate/MedlineDate", default="")[:4]
                or "")
        mesh = [m.findtext("DescriptorName", default="") for m in
                (med.findall(".//MeshHeadingList/MeshHeading") or [])]
        doi = next((a.text for a in
                    article.findall(".//ELocationID[@EIdType='doi']") or []), "")
        lang = article.findtext("Language", default="eng")
        out.append({"pmid": pmid_el.text, "title": title.strip(),
                    "abstract": text.strip(), "pub_date": year,
                    "mesh_terms": "; ".join(m for m in mesh if m),
                    "doi": doi or "", "language": lang, "topic": topic})
    return out


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict] = []
    for topic, term in TOPICS.items():
        try:
            pmids = esearch(term, PER_TOPIC)
            print(f"[{topic}] esearch → {len(pmids)} pmids")
        except Exception as exc:
            print(f"❌ esearch {topic}: {type(exc).__name__}: {exc} — "
                  "descarga declarada fallida, sin inventar datos")
            return 1
        rows = []
        for i in range(0, len(pmids), BATCH):
            batch = pmids[i:i + BATCH]
            try:
                rows.extend(parse_articles(efetch(batch), topic))
            except Exception as exc:
                print(f"❌ efetch {topic} batch {i}: {type(exc).__name__}")
                return 1
            time.sleep(0.4)  # ≤3 req/s sin clave
        # dedupe por pmid y recorte al cupo
        seen, unique = set(), []
        for r in rows:
            if r["pmid"] not in seen:
                seen.add(r["pmid"])
                unique.append(r)
        unique = unique[:PER_TOPIC]
        print(f"[{topic}] {len(unique)} abstracts válidos")
        all_rows.extend(unique)
        time.sleep(0.4)

    jsonl = DATA / "pubmed_pilot.jsonl"
    with open(jsonl, "w", encoding="utf-8") as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        table = pa.Table.from_pylist(all_rows)
        pq.write_table(table, DATA / "pubmed_pilot.parquet")
        formato = "parquet+jsonl"
    except ImportError:
        formato = "jsonl (pyarrow no instalado)"
    manifest = {
        "downloaded_at": datetime.now().isoformat(timespec="seconds"),
        "n_abstracts": len(all_rows),
        "per_topic": {t: sum(1 for r in all_rows if r["topic"] == t)
                      for t in TOPICS},
        "source": "NCBI E-utilities (esearch sort=relevance, 5 años)",
        "format": formato,
        "gold_declaration": "topic = etiqueta de sourcing (silver-gold, "
                            "sin anotación humana) — ver PREREG_QUALITY.md",
    }
    (DATA / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False))
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
