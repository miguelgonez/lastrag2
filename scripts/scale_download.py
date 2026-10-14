#!/usr/bin/env python3
"""
Escala — Descarga resumible de 50 k abstracts PubMed (4 temas × 12.500).
=========================================================================
esearch paginado (usehistory) + efetch por lotes de 200, ≤3 req/s sin clave.
Estado por tema en cierre_brecha_real/data/scale_state.json (re-ejecutable).
Salida: pubmed_scale.jsonl (+ parquet si pyarrow) + MANIFEST_SCALE.json.
El gold MeSH-estricto se evalúa en el loop (aquí solo se guardan mesh_terms).
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
    "t2d_general": '"Diabetes Mellitus, Type 2"[MeSH Terms]',
    "hypertension": '("Antihypertensive Agents"[MeSH Terms] OR ("hypertension"[MeSH Terms] AND therapy[MeSH Subheading]))',
}
PER_TOPIC = 12500
BATCH = 200
UA = {"User-Agent": "lastrag2-scale/1.0 (research; repo maintainer)"}
STATE = DATA / "scale_state.json"


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def esearch_ids(term: str, n: int, mindate: str = "", maxdate: str = "") -> list[str]:
    """Por slice anual (Adenda 1): esconde el cap de ~10k por consulta."""
    ids, retstart = [], 0
    webenv = querykey = None
    while len(ids) < n:
        params = {"db": "pubmed", "term": term, "retmode": "json",
                  "datetype": "pdat",
                  "sort": "relevance", "retmax": min(9999, n - len(ids)),
                  "retstart": retstart, "usehistory": "y"}
        if mindate and maxdate:
            params.update({"mindate": mindate, "maxdate": maxdate})
        q = urllib.parse.urlencode(params)
        raw = get(f"{EUTILS}/esearch.fcgi?{q}")
        try:
            data = json.loads(raw)["esearchresult"]
        except json.JSONDecodeError:
            # NCBI a veces devuelve caracteres de control en el JSON:
            # strict=False los tolera (contenido idéntico, parser menos quisquilloso)
            data = json.loads(raw.decode("utf-8", "replace"), strict=False)["esearchresult"]
        if webenv is None:
            webenv, querykey = data.get("webenv"), data.get("querykey")
        batch = [str(p) for p in data.get("idlist", [])]
        if not batch:
            break
        ids.extend(batch)
        retstart += len(batch)
        time.sleep(0.38)
    seen, unique = set(), []
    for p in ids:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique[:n]


def efetch_parse(pmids: list[str], topic: str) -> list[dict]:
    q = urllib.parse.urlencode({"db": "pubmed", "retmode": "xml",
                                "id": ",".join(pmids)})
    root = ET.fromstring(get(f"{EUTILS}/efetch.fcgi?{q}"))
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
        if not title or len(text) < 200:
            continue
        year = (article.findtext(".//PubDate/Year")
                or article.findtext(".//PubDate/MedlineDate", default="")[:4] or "")
        mesh = [m.findtext("DescriptorName", default="") for m in
                (med.findall(".//MeshHeadingList/MeshHeading") or [])]
        doi = next((a.text for a in
                    article.findall(".//ELocationID[@EIdType='doi']") or []), "")
        out.append({"pmid": pmid_el.text, "title": title.strip(),
                    "abstract": text.strip(), "pub_date": year,
                    "mesh_terms": "; ".join(m for m in mesh if m),
                    "doi": doi or "", "language": article.findtext("Language", default="eng"),
                    "topic": topic})
    return out


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {"topics_done": [], "rows": []}
    YEARS = [("2021", "2021/01/01", "2021/12/31"),
             ("2022", "2022/01/01", "2022/12/31"),
             ("2023", "2023/01/01", "2023/12/31"),
             ("2024", "2024/01/01", "2024/12/31"),
             ("2025", "2025/01/01", "2025/12/31"),
             ("2026", "2026/01/01", "2026/12/31")]
    PER_SLICE = 2100  # 6 años × 2100 ≈ 12.600 por tema
    for topic, term in TOPICS.items():
        if topic in state["topics_done"]:
            print(f"[{topic}] ya completo (resumible) — skip")
            continue
        t0 = time.time()
        pmids = []
        try:
            for yname, mind, mxd in YEARS:
                key = f"{topic}:{yname}"
                if key in state["topics_done"]:
                    continue
                got = esearch_ids(term, PER_SLICE, mind, mxd)
                print(f"[{key}] esearch → {len(got)} pmids")
                pmids.extend(g for g in got if g not in set(pmids))
                state["topics_done"].append(key)
                STATE.write_text(json.dumps(state))
                time.sleep(0.38)
            pmids = pmids[:PER_TOPIC]
        except Exception as exc:
            print(f"❌ esearch {topic}: {type(exc).__name__}: {exc} — declarado, nada inventado")
            STATE.write_text(json.dumps(state))
            return 1
        rows = []
        for i in range(0, len(pmids), BATCH):
            try:
                rows.extend(efetch_parse(pmids[i:i + BATCH], topic))
            except Exception as exc:
                print(f"❌ efetch {topic}@{i}: {type(exc).__name__} — estado parcial conservado")
                STATE.write_text(json.dumps(state))
                return 1
            if (i // BATCH) % 10 == 0:
                print(f"[{topic}] {i + BATCH}/{len(pmids)} lotes · {len(rows)} válidos", flush=True)
            time.sleep(0.38)
        seen = {r["pmid"] for r in state["rows"]}
        state["rows"].extend(r for r in rows if r["pmid"] not in seen)
        state["topics_done"].append(topic)
        STATE.write_text(json.dumps(state))
        print(f"[{topic}] ✓ {len(rows)} abstracts ({time.time()-t0:.0f}s)")

    jsonl = DATA / "pubmed_scale.jsonl"
    with open(jsonl, "w", encoding="utf-8") as f:
        for r in state["rows"]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        pq.write_table(pa.Table.from_pylist(state["rows"]),
                       DATA / "pubmed_scale.parquet")
        fmt = "parquet+jsonl"
    except ImportError:
        fmt = "jsonl"
    per = {t: sum(1 for r in state["rows"] if r["topic"] == t) for t in TOPICS}
    manifest = {"downloaded_at": datetime.now().isoformat(timespec="seconds"),
                "n_abstracts": len(state["rows"]), "per_topic": per,
                "format": fmt, "gold": "MeSH-estricto en el loop "
                "(PREREG_SCALE.md); descriptor por tema declarado allí"}
    (DATA / "MANIFEST_SCALE.json").write_text(json.dumps(manifest, indent=2,
                                                         ensure_ascii=False))
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
