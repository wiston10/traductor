#!/usr/bin/env python3
"""
Mide cuánto acierta Whisper, usando las frases corregidas a mano.

  python3 evaluate.py
      Acierto EN DIRECTO: compara lo que Whisper escribió durante el culto con la corrección.
      No carga el modelo: tarda un segundo.

  python3 evaluate.py --model <modelo HF> [--vocab]
      Vuelve a transcribir las frases de las sesiones de PRUEBA con ese modelo/ajustes y
      compara. Sirve para decidir si un modelo nuevo, un modelo entrenado o --vocab es mejor.

Resultado: porcentaje de error de palabras (WER). Más bajo = mejor.
"""
from __future__ import annotations

import argparse
import csv
import wave
from collections import Counter
from pathlib import Path

import numpy as np

import training_store as store

HERE = Path(__file__).resolve().parent


def done_segments(root: Path, purpose: str | None):
    for s in store.list_sessions(root):
        if purpose and s["purpose"] != purpose:
            continue
        d = root / s["id"]
        for seg in store.load_segments(d):
            if seg["status"] in ("ok", "corrected"):
                yield s, d, seg


def missed_words(pairs) -> Counter:
    """Palabras de la corrección que no aparecen en lo transcrito (lo que más falla)."""
    c = Counter()
    for ref, hyp in pairs:
        h = Counter(store.normalize(hyp))
        for w in store.normalize(ref):
            if h[w] > 0:
                h[w] -= 1
            elif len(w) > 2:
                c[w] += 1
    return c


def report(title: str, rows: list[tuple[str, str, str]]) -> None:
    """rows = (sesión, referencia, transcripción)"""
    if not rows:
        print(f"\n{title}: no hay frases corregidas todavía.")
        return
    print(f"\n{title}")
    by_session: dict[str, list] = {}
    for sid, ref, hyp in rows:
        by_session.setdefault(sid, []).append((ref, hyp))
    for sid, pairs in by_session.items():
        print(f"  {sid}: {store.wer(pairs) * 100:5.1f} % de error  ({len(pairs)} frases)")
    allp = [(r, h) for _, r, h in rows]
    words = sum(len(store.normalize(r)) for r, _ in allp)
    print(f"  TOTAL: {store.wer(allp) * 100:5.1f} % de error en {len(allp)} frases / {words} palabras")
    top = missed_words(allp).most_common(15)
    if top:
        print("  Palabras que más falla (candidatas para vocab/de.txt):", ", ".join(f"{w} ({n})" for w, n in top))


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=str(HERE / "training-data"))
    ap.add_argument("--model", help="Volver a transcribir las sesiones de prueba con este modelo")
    ap.add_argument("--vocab", nargs="?", const=str(HERE / "vocab" / "de.txt"), default="")
    ap.add_argument("--engine", choices=("torch", "mlx"), default="torch", help="Motor para --model")
    ap.add_argument("--csv", help="Guardar el detalle frase a frase en este CSV")
    args = ap.parse_args()
    root = Path(args.data_dir)

    live = [(s["id"], seg["text"], seg["auto_text"]) for s, _d, seg in done_segments(root, None)]
    report("ACIERTO EN DIRECTO (todas las sesiones corregidas)", live)
    test_live = [(s["id"], seg["text"], seg["auto_text"]) for s, _d, seg in done_segments(root, "test")]
    report("ACIERTO EN DIRECTO (solo sesiones de prueba)", test_live)

    rows = test_live
    if args.model:
        from server import make_transcriber  # carga el motor solo si hace falta
        vocab = " ".join(Path(args.vocab).read_text(encoding="utf-8").split()) if args.vocab else ""
        tr = make_transcriber(args.engine, args.model, None, "de", vocab)
        rows = []
        segs = list(done_segments(root, "test"))
        for i, (s, d, seg) in enumerate(segs, 1):
            hyp = tr._run(read_wav(d / seg["file"]))
            rows.append((s["id"], seg["text"], hyp))
            print(f"\r  transcribiendo {i}/{len(segs)}…", end="", flush=True)
        print()
        report(f"MODELO {args.model} [{args.engine}]{' + vocab' if vocab else ''} (sesiones de prueba)", rows)

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["sesion", "referencia", "transcripcion", "errores", "palabras"])
            for sid, ref, hyp in rows:
                e, n = store.word_errors(ref, hyp)
                w.writerow([sid, ref, hyp, e, n])
        print(f"\nDetalle guardado en {args.csv}")


if __name__ == "__main__":
    main()
