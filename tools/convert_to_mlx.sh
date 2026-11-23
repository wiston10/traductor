#!/usr/bin/env bash
# Convierte el modelo Whisper suizo-alemán al formato MLX (una sola vez, ~5 minutos).
# Usa el conversor oficial de Apple: https://github.com/ml-explore/mlx-examples/tree/main/whisper
#
#   bash tools/convert_to_mlx.sh                       # el modelo suizo por defecto
#   bash tools/convert_to_mlx.sh <otro/modelo-de-HF>   # otro modelo ajustado de Hugging Face
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRV="$ROOT/apps/whisper-server"
PY="$SRV/.venv/bin/python"
MODEL="${1:-Flurin17/whisper-large-v3-turbo-swiss-german}"
OUT="$SRV/models/swiss-german-turbo-mlx"
[ "$MODEL" != "Flurin17/whisper-large-v3-turbo-swiss-german" ] && OUT="$SRV/models/$(basename "$MODEL")-mlx"
REPO="$ROOT/data/mlx-examples"

if [ ! -x "$PY" ]; then
  echo "Falta el entorno de Python. Créalo antes (ver apps/whisper-server/README.md)."
  exit 1
fi
if [ "$(uname -m)" != "arm64" ]; then
  echo "MLX solo funciona en Mac con chip Apple (M1 o posterior)."
  exit 1
fi

echo "1/3 Instalando MLX…"
"$PY" -m pip install -q -r "$SRV/requirements-mlx.txt"

echo "2/3 Descargando el conversor oficial (mlx-examples)…"
if [ ! -d "$REPO/.git" ]; then
  git clone --depth 1 https://github.com/ml-explore/mlx-examples.git "$REPO"
else
  git -C "$REPO" pull --ff-only -q || true
fi
# La lista de dependencias del conversor ha cambiado de sitio entre versiones
for req in "$REPO/whisper/requirements.txt" "$REPO/whisper/mlx_whisper/requirements.txt"; do
  if [ -f "$req" ]; then "$PY" -m pip install -q -r "$req"; break; fi
done

if [ -f "$OUT/config.json" ] && [ "${FORCE:-0}" != "1" ]; then
  echo "3/3 El modelo ya estaba convertido en $OUT (para repetir: FORCE=1 bash tools/convert_to_mlx.sh)"
else
  echo "3/3 Convirtiendo $MODEL → $OUT  (descarga ~1,6 GB la primera vez)"
  cd "$REPO/whisper"
  "$PY" convert.py --torch-name-or-path "$MODEL" --mlx-path "$OUT" --dtype float16
fi

# mlx-whisper 0.4.x busca «weights.safetensors»; el conversor nuevo guarda «model.safetensors»
if [ -f "$OUT/model.safetensors" ] && [ ! -f "$OUT/weights.safetensors" ]; then
  mv "$OUT/model.safetensors" "$OUT/weights.safetensors"
fi

if [ -f "$OUT/config.json" ]; then
  echo
  echo "✔ Listo. Pruébalo:"
  echo "    npm run bench"
  echo "  y en directo:"
  echo "    npm start -- --engine mlx"
else
  echo "✕ La conversión no generó $OUT/config.json. Copia el error de arriba y compártelo."
  exit 1
fi
