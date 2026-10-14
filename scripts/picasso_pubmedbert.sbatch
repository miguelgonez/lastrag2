#!/bin/bash
#SBATCH --job-name=lastrag-pubmedbert
#SBATCH --partition=gpu_partition
#SBATCH --qos=short                          # QOS de casa (≤120 min)
#SBATCH --constraint=b200                    # features nodo: dgx,gpu,b200
#SBATCH --gres=gpu:1                     # 1× B200 (180 GB HBM3e)
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=01:00:00                  # QOS short ≤120 min (gotcha casa)
#SBATCH --output=pubmedbert_%j.log       # logs caen en cwd (gotcha casa)

# Tercera vía biomédica en Picasso B200 — EJECUCIÓN PENDIENTE (declarada).
# Preparación (una vez, desde el login):
#   1. scp el repo:      rsync -a core/ scripts/ cierre_brecha_real/data/pubmed_scale.parquet \
#                          picasso:~/lastrag_scale/
#   2. Entorno:          module load python/3.11 (o el disponible ≥3.10) &&
#                        pip install --user numpy pyarrow torch transformers
#   3. Correr:           sbatch scripts/picasso_pubmedbert.sbatch
# Post: traer de vuelta scale_embeddings_biomed_*.npz y ejecutar
#       calidad_scale_loop.py en el MBP (la vía biomédica la detecta sola).

set -euo pipefail
# módulo dentro del job (sbatch NO hereda los module load del login)
module load python/3.11.4
cd "$SLURM_SUBMIT_DIR"   # NUNCA dirname $0: en sbatch apunta al spool
echo "GPU: ${CUDA_VISIBLE_DEVICES:-?} · $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"

# corpus: parquet → jsonl (el loop lee jsonl; si ya existe, se respeta)
python3 - <<'PY'
import json, pathlib
try:
    import pyarrow.parquet as pq
    src = pathlib.Path("cierre_brecha_real/data/pubmed_scale.parquet")
    dst = pathlib.Path("cierre_brecha_real/data/pubmed_scale.jsonl")
    if src.exists() and not dst.exists():
        t = pq.read_table(src)
        with open(dst, "w", encoding="utf-8") as f:
            for r in t.to_pylist():
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("jsonl regenerado desde parquet:", dst)
except Exception as exc:
    print("aviso: parquet→jsonl:", type(exc).__name__)
PY

# embeddings biomédicos (PubMedBERT en B200; fallback declarado si algo falla)
python3 "$SLURM_SUBMIT_DIR/scripts/scale_embeddings.py" --engine torch --biomed

echo "✅ si todo fue bien: recoger cierre_brecha_real/data/scale_embeddings_biomed_*.npz"
