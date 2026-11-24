#!/usr/bin/env bash
# Instala la traducción NLLB-200 en el servidor (una sola vez, ~600 MB).
#   bash tools/setup_nllb.sh          (o: npm run setup:nllb)
#   FORCE=1 bash tools/setup_nllb.sh  (volver a convertir)
# Licencia del modelo: CC BY-NC 4.0 → solo uso NO comercial.
set -euo pipefail
cd "$(dirname "$0")/../apps/whisper-server"

if [ ! -x .venv/bin/python ]; then
  echo "Falta el entorno de Python. Primero:  cd apps/whisper-server && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

OUT=models/nllb-600m-ct2
if [ -f "$OUT/model.bin" ] && [ "${FORCE:-0}" != "1" ]; then
  echo "NLLB ya está convertido en $OUT (FORCE=1 para repetir)."
else
  echo "1/3 Instalando CTranslate2 y sentencepiece…"
  .venv/bin/pip install -r requirements-mt.txt
  echo "2/3 Descargando y convirtiendo facebook/nllb-200-distilled-600M a int8 (unos minutos)…"
  mkdir -p models
  if ! .venv/bin/ct2-transformers-converter --model facebook/nllb-200-distilled-600M \
        --quantization int8 --output_dir "$OUT" --force; then
    echo
    echo "La conversión falló (puede ser una versión de transformers que CTranslate2 aún no admite)."
    echo "Alternativa sin convertir (más lenta):  npm start -- --translate transformers"
    exit 1
  fi
fi

echo "3/3 Prueba rápida…"
.venv/bin/python - <<'PY'
import translate as T
svc = T.TranslationService(T.load_backend("ct2"))
out = svc.translate_sync("Gott hat uns nicht einen Geist der Furcht gegeben.", "de", ["es", "en", "zh"])
for k, v in out.items():
    print(f"  {k}: {v}")
PY
echo
echo "Listo. Al arrancar (npm start) el servidor traducirá solo. Mide la velocidad con:  npm run bench:mt"
