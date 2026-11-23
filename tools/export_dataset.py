#!/usr/bin/env python3
"""
Exporta las frases corregidas a un conjunto de datos listo para entrenar Whisper
(formato «audiofolder» de Hugging Face, el que usan los cuadernos de Kaggle/Colab).

  python3 tools/export_dataset.py

Resultado (no va a git):
  data/dataset/
    train/metadata.csv + *.wav     <- sesiones marcadas «Entrenamiento»
    test/metadata.csv  + *.wav     <- sesiones marcadas «Prueba»: NUNCA se entrenan con ellas
    README.txt                     <- resumen (horas, frases)

Solo se exportan frases «correctas» o «corregidas»; las pendientes y descartadas no.
"""
from __future__ import annotations

import argparse
import csv
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "whisper-server"))
import training_store as store  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=str(ROOT / "apps" / "whisper-server" / "training-data"))
    ap.add_argument("--out", default=str(ROOT / "data" / "dataset"))
    ap.add_argument("--min-seconds", type=float, default=0.8, help="Descartar frases más cortas")
    ap.add_argument("--max-seconds", type=float, default=30.0, help="Whisper no admite más de 30 s")
    args = ap.parse_args()
    src, out = Path(args.data_dir), Path(args.out)

    if out.exists():
        shutil.rmtree(out)
    stats = {"train": [0, 0.0], "test": [0, 0.0]}
    skipped = 0
    writers = {}
    files = {}
    for split in stats:
        (out / split).mkdir(parents=True)
        files[split] = open(out / split / "metadata.csv", "w", newline="", encoding="utf-8")
        writers[split] = csv.writer(files[split])
        writers[split].writerow(["file_name", "transcription", "session", "auto_text"])

    for sess in store.list_sessions(src):
        split = "test" if sess["purpose"] == "test" else "train"
        d = src / sess["id"]
        for seg in store.load_segments(d):
            if seg["status"] not in ("ok", "corrected"):
                continue
            if not (args.min_seconds <= seg["duration"] <= args.max_seconds) or not seg["text"].strip():
                skipped += 1
                continue
            name = f"{sess['id']}_{seg['id']}.wav"
            shutil.copyfile(d / seg["file"], out / split / name)
            writers[split].writerow([name, seg["text"], sess["id"], seg["auto_text"]])
            stats[split][0] += 1
            stats[split][1] += seg["duration"]

    for f in files.values():
        f.close()
    lines = [f"Conjunto exportado el {date.today().isoformat()}"]
    for split, (n, sec) in stats.items():
        lines.append(f"  {split}: {n} frases, {sec / 3600:.2f} h")
    lines.append(f"  omitidas por duración o texto vacío: {skipped}")
    if stats["test"][0] == 0:
        lines.append("  AVISO: no hay sesiones de PRUEBA. Marca al menos una como «Prueba» en /corregir "
                     "para poder medir si el entrenamiento mejora algo.")
    if stats["train"][1] < 5 * 3600:
        lines.append("  Nota: con menos de ~5 h de entrenamiento la mejora suele ser pequeña; "
                     "el objetivo razonable es 10–20 h.")
    (out / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
