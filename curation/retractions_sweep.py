#!/usr/bin/env python3
"""Barrido de retractaciones del corpus PubMed (instrumento de curación, capa 5).

Ejecuta el proceso aprobado por el arquitecto (23-oct-2026):
  1. Extrae PMIDs (+DOI) de los ficheros jsonl del corpus.
  2. PubMed E-utilities (efetch XML, lotes de 200) → PublicationType
     «Retracted Publication» / «Expression of Concern» por PMID.
  3. Retraction Watch DB (Crossref GitLab CSV) → coincidencia por PMID
     (columna OriginalPaperPubMedID) con respaldo por DOI.
  4. Fusión (regla aprobada): retractado/expresión en CUALQUIER fuente ⇒ ese
     estado; retraction_source = pubmed | rwdb | pubmed+rwdb; discrepancia
     anotada, jamás promediada. Hallazgo = evento (re-estampa inmediata).
  5. Estampa TODO el corpus (status none incluido) con
     retraction_checked_at — sin comprobación fechada y con fuente, la capa 5
     no cualifica (RETRACTION_CHECK_UNSOURCED).

Salidas (en --out): source_meta_<fecha>.json (contrato capa 5) ·
RETRACTIONS_RECEIPT_<fecha>.json (recibo contable) · pmids.txt.

Solo stdlib. Sin API key: ≤3 req/s (0.34 s entre lotes); con NCBI_API_KEY: 10.
Re-ejecutable: retoma el checkpoint pubmed_partial.json si existe.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
RWDB_URL = ("https://gitlab.com/crossref/retraction-watch-data/-/raw/main/"
            "retraction_watch.csv")
BATCH = 200
SIN_KEY, CON_KEY = 0.38, 0.12          # cortesía entre lotes (s)
RETRACTED_PT = "Retracted Publication"
CONCERN_PT = "Expression of Concern"


def log(msg: str) -> None:
    print(msg, flush=True)


def load_corpus(files: list[Path]) -> tuple[dict[str, str], dict]:
    """PMID→DOI de los jsonl; cuenta duplicados entre ficheros."""
    pmids: dict[str, str] = {}
    stats = {"files": {}, "duplicates_within_union": 0}
    for f in files:
        n = 0
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            pid = str(row.get("pmid") or row.get("PMID") or "").strip()
            if not pid:
                continue
            doi = (row.get("doi") or row.get("DOI") or "").strip() or pmids.get(pid, "")
            if pid in pmids:
                stats["duplicates_within_union"] += 1
            pmids[pid] = doi
            n += 1
        stats["files"][str(f)] = n
    return pmids, stats


# ── fase PubMed ───────────────────────────────────────────────────────────

def efetch_statuses(all_pmids: list[str], checkpoint: Path) -> dict[str, str]:
    done: dict[str, str] = {}
    if checkpoint.exists():
        done = json.loads(checkpoint.read_text())
        log(f"checkpoint: {len(done)} PMIDs ya comprobados — se retoma")
    api_key = os.environ.get("NCBI_API_KEY", "")
    delay = CON_KEY if api_key else SIN_KEY
    pending = [p for p in all_pmids if p not in done]
    batches = [pending[i:i + BATCH] for i in range(0, len(pending), BATCH)]
    log(f"PubMed: {len(pending)} PMIDs pendientes en {len(batches)} lotes de {BATCH}")
    t0 = time.time()
    for i, batch in enumerate(batches, 1):
        params = {"db": "pubmed", "retmode": "xml", "id": ",".join(batch)}
        if api_key:
            params["api_key"] = api_key
        url = EFETCH + "?" + urllib.parse.urlencode(params)
        xml_text = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "lastrag-foundation-curation/1.0"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    xml_text = r.read().decode("utf-8", "replace")
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
                wait = 2 * (attempt + 1) ** 2
                log(f"  lote {i}: {type(e).__name__} — reintento en {wait}s ({attempt+1}/3)")
                time.sleep(wait)
        if xml_text is None:
            log(f"  lote {i}: FALLO definitivo — se guarda checkpoint y se aborta")
            break
        for pmid, status in parse_pubmed_batch(xml_text).items():
            done[pmid] = status
        for pid in batch:                      # sin artículo = desconocido, no ausente
            done.setdefault(pid, "unknown")
        if i % 10 == 0 or i == len(batches):
            checkpoint.write_text(json.dumps(done))
            rate = len([p for p in done]) / max(time.time() - t0, 1)
            log(f"  lote {i}/{len(batches)} · {len(done)} comprobados · {rate:.0f} PMID/s")
        time.sleep(delay)
    checkpoint.write_text(json.dumps(done))
    return done


def parse_pubmed_batch(xml_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for art in root.iter("PubmedArticle"):
        pmid_el = art.find("./MedlineCitation/PMID")
        if pmid_el is None or not (pmid_el.text or "").strip():
            continue
        pmid = pmid_el.text.strip()
        types = [(t.text or "").strip() for t in
                 art.findall("./MedlineCitation/Article/PublicationTypeList/PublicationType")]
        if RETRACTED_PT in types:
            out[pmid] = "retracted"
        elif CONCERN_PT in types:
            out[pmid] = "concern"
        else:
            out[pmid] = "none"
    return out


# ── fase Retraction Watch ─────────────────────────────────────────────────

def rwdb_statuses(csv_path: Path, pmid2doi: dict[str, str]) -> tuple[dict[str, str], dict]:
    if not csv_path.exists():
        log(f"descargando RWDB ({RWDB_URL})…")
        urllib.request.urlretrieve(RWDB_URL, csv_path)
    sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    doi2pmid = {d.lower(): p for p, d in pmid2doi.items() if d}
    out: dict[str, str] = {}
    n_rows = 0
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        cols = set(reader.fieldnames or [])
        pmid_col = next((c for c in ("OriginalPaperPubMedID", "OriginalPaperPMID", "PMID")
                         if c in cols), None)
        doi_col = next((c for c in ("OriginalPaperDOI", "DOI") if c in cols), None)
        nature_col = "RetractionNature" if "RetractionNature" in cols else None
        for row in reader:
            n_rows += 1
            pmid = (row.get(pmid_col) or "").strip() if pmid_col else ""
            if not pmid and doi_col:
                pmid = doi2pmid.get((row.get(doi_col) or "").strip().lower(), "")
            if not pmid:
                continue
            nature = (row.get(nature_col) or "").strip().lower() if nature_col else ""
            status = "concern" if "concern" in nature else "retracted"
            prev = out.get(pmid)
            if prev is None or (prev == "none") or (status == "retracted" and prev == "concern"):
                out[pmid] = status
    meta = {"csv_sha256": sha, "rows": n_rows, "pmid_column": pmid_col,
            "doi_fallback_used": bool(doi_col and not pmid_col)}
    return out, meta


# ── fusión y salidas ──────────────────────────────────────────────────────

def worst(a: str, b: str) -> str:
    order = {"retracted": 2, "concern": 1, "none": 0, "unknown": 0}
    return a if order.get(a, 0) >= order.get(b, 0) else b


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", nargs="+", required=True, type=Path,
                    help="ficheros jsonl del corpus (pmid, doi)")
    ap.add_argument("--out", required=True, type=Path, help="directorio de salida")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()

    pmid2doi, corpus_stats = load_corpus(args.corpus)
    all_pmids = sorted(pmid2doi)
    log(f"corpus: {len(all_pmids)} PMIDs únicos de {len(args.corpus)} ficheros")

    pubmed = efetch_statuses(all_pmids, args.out / "pubmed_partial.json")
    rwdb, rwdb_meta = rwdb_statuses(args.out / "retraction_watch.csv", pmid2doi)

    source_meta, receipt_flags = {}, {"retracted": [], "concern": [], "discrepancies": []}
    for pid in all_pmids:
        ps, rs = pubmed.get(pid, "unknown"), rwdb.get(pid, "none")
        final = worst(ps, rs)
        flagged = [s for s, st in (("pubmed", ps), ("rwdb", rs)) if st in ("retracted", "concern")]
        src = "+".join(flagged) if flagged else "pubmed+rwdb"  # none: ambas consultadas
        note = None
        if len(flagged) == 1:
            note = f"discrepancia: solo {flagged[0]} marca ({ps} vs rwdb {rs})"
            receipt_flags["discrepancies"].append(pid)
        if final in ("retracted", "concern"):
            receipt_flags[final].append(pid)
        entry = {"tier": "peer_reviewed", "retraction_status": final,
                 "retraction_checked_at": today, "retraction_source": src,
                 "identifier": pid}
        if note:
            entry["note"] = note
        source_meta[pid] = entry

    stamp = today.replace("-", "")
    (args.out / f"source_meta_{stamp}.json").write_text(
        json.dumps(source_meta, ensure_ascii=False, indent=1))
    (args.out / "pmids.txt").write_text("\n".join(all_pmids) + "\n")
    counts = {s: sum(1 for v in source_meta.values() if v["retraction_status"] == s)
              for s in ("none", "retracted", "concern", "unknown")}
    receipt = {
        "run_date": today, "corpus": corpus_stats, "n_unique_pmids": len(all_pmids),
        "pubmed": {"checked": len(pubmed),
                   "retracted": sum(1 for v in pubmed.values() if v == "retracted"),
                   "concern": sum(1 for v in pubmed.values() if v == "concern")},
        "rwdb": rwdb_meta | {"matched_in_corpus": len([p for p in rwdb if p in pmid2doi]),
                             "retracted": sum(1 for v in rwdb.values() if v == "retracted"),
                             "concern": sum(1 for v in rwdb.values() if v == "concern")},
        "final_counts": counts,
        "discrepancies_n": len(receipt_flags["discrepancies"]),
        "discrepancies_pmids": receipt_flags["discrepancies"][:50],
        "retracted_pmids": receipt_flags["retracted"][:200],
        "concern_pmids": receipt_flags["concern"][:100],
        "policy": "arquitecto 23-oct: hallazgo=evento; union peor-estado; fuente por documento; discrepancia anotada",
        "tool": "curation/retractions_sweep.py v1.0",
    }
    (args.out / f"RETRACTIONS_RECEIPT_{stamp}.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2))
    log(f"HECHO: {counts} · discrepancias {len(receipt_flags['discrepancies'])}")
    log(f"salidas: {args.out}/source_meta_{stamp}.json · RETRACTIONS_RECEIPT_{stamp}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
