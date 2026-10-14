#!/usr/bin/env python3
"""
Fase 1 — Ingesta del piloto PubMed a Delta Lake (Apache Spark)
================================================================
Parte del parquet de Fase 0 (cierre_brecha_real/data/pubmed_pilot.parquet)
y lo materializa en Delta particionado por (topic, year).

NOTA de esquema: `pub_date` del piloto es un AÑO en texto ("2024"), no una
fecha ISO — se castea a int con coalesce(0); no hay to_date (daría null).

Uso en el host Spark (docker, sin instalar nada en el anfitrión):
  docker run --rm -v <dir_repo>:/work \
    --entrypoint /opt/spark/bin/spark-submit apache/spark-py:v3.5.4 \
    --packages io.delta:delta-spark_2.12:3.2.0 /work/scripts/ingest_pubmed_delta.py

DELTA_PATH es sobreescribible por env (default: junto al parquet, para que
sobreviva al contenedor al estar en el volumen montado).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql.functions import coalesce, col, lit

ROOT = Path(__file__).resolve().parents[1]
PILOT_PARQUET = Path(os.environ.get(
    "PILOT_PARQUET", ROOT / "cierre_brecha_real" / "data" / "pubmed_pilot.parquet"))
DELTA_PATH = os.environ.get(
    "DELTA_PATH", str(ROOT / "cierre_brecha_real" / "data" / "delta_pubmed"))


def main():
    spark = (
        SparkSession.builder
        .appName("LastRAG-PubMed-Pilot-Delta")
        .config("spark.sql.extensions",
                "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .getOrCreate()
    )
    print(f"[fase1] spark {spark.version}")
    print(f"[fase1] parquet de entrada: {PILOT_PARQUET}")

    df = spark.read.parquet(str(PILOT_PARQUET))
    # pub_date = año en texto → int; sin fecha inventada (coalesce 0 declarado)
    df = df.withColumn("year", coalesce(col("pub_date").cast("int"), lit(0)))

    n_in = df.count()
    print(f"[fase1] registros leídos: {n_in}")
    df.groupBy("topic").count().orderBy("topic").show(truncate=False)

    (df.write.format("delta").mode("overwrite")
       .partitionBy("topic", "year").save(DELTA_PATH))
    print(f"[fase1] delta escrito en: {DELTA_PATH}")

    delta_df = spark.read.format("delta").load(DELTA_PATH)
    n_out = delta_df.count()
    print(f"[fase1] verificación: {n_out} registros leídos de Delta")
    if n_out != n_in:
        print(f"[fase1] ❌ DESCUADRE {n_in} ≠ {n_out}")
        spark.stop()
        return 1
    delta_df.groupBy("topic", "year").count().orderBy("topic", "year").show(10,
                                                                            truncate=False)
    delta_df.select("pmid", "topic", "year", "title").show(5, truncate=60)
    print(f"[fase1] ✅ OK {n_in} = {n_out} (particiones topic×year)")
    spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
