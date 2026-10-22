#!/usr/bin/env bash
# fork de lastrag-foundation para un proyecto nuevo (política canon v1.3.0:
# forkable but contract-compatible). Estampa procedencia en FORK.json.
set -euo pipefail

MASTER="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:?uso: fork.sh <dir_destino> [nombre_proyecto]}"
NAME="${2:-$(basename "$TARGET")}"
COMMIT="$(git -C "$MASTER" rev-parse HEAD)"
TREE="$(git -C "$MASTER" rev-parse HEAD^{tree})"

if [ -e "$TARGET" ]; then
  echo "ERROR: $TARGET ya existe; un fork nuevo exige destino ausente." >&2
  exit 1
fi

git clone --quiet "$MASTER" "$TARGET"

cat > "$TARGET/FORK.json" <<EOF
{
  "fork_of": "lastrag-foundation",
  "master_path": "$MASTER",
  "project": "$NAME",
  "created": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "master_commit": "$COMMIT",
  "master_tree": "$TREE",
  "canon": "OMEGA-MR2-LASTRAG-FOUNDATION-CANON v1.3.0",
  "policy": "forkable but contract-compatible; CONTRACT_VERSION 1.0",
  "rule": "las necesidades del proyecto se desarrollan en ESTE fork; el master no se modifica in situ. Mejoras horizontales -> propuesta de commit al master con changelog."
}
EOF

# El upstream pasa a llamarse upstream-master con push DESHABILITADO:
# comparar/difuminar sí, escribir en el master no (blindaje mecánico del canon).
git -C "$TARGET" remote rename origin upstream-master
git -C "$TARGET" remote set-url --push upstream-master DISABLE_PUSH_MASTER
git -C "$TARGET" add FORK.json
git -C "$TARGET" commit --quiet -m "fork: nace '$NAME' desde lastrag-foundation $COMMIT (procedencia estampada en FORK.json)"

echo "Fork creado: $TARGET"
echo "  master_commit: $COMMIT"
echo "  master_tree:   $TREE"
echo "Registrar el fork en FORKS.md del master (append a la tabla)."
