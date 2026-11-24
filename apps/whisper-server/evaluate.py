#!/usr/bin/env python3
"""
Mide cuánto acierta Whisper, usando las frases corregidas a mano.

  python3 evaluate.py
      Acierto EN DIRECTO: compara lo que Whisper escribió durante el culto con la corrección.
      No carga el modelo: tarda un segundo.

  python3 evaluate.py --model <modelo HF> [--vocab] [--beam 3] [--context confirmed] [--gate-db -45]
      Vuelve a transcribir las frases de las sesiones de PRUEBA con ese modelo/ajustes y
      compara. Sirve para decidir si un modelo nuevo, un modelo entrenado, --vocab, beam
      o el contexto son mejores. Muestra también el tiempo medio por frase.
      «--model suizo» = el modelo por defecto.

  python3 evaluate.py --sugerir-dialecto
      Lista las palabras que Whisper escribió y tú corregiste siempre igual
      (p. ej. «nöd» → «nicht»). Revísalas y copia las buenas a vocab/dialecto-de.json.

Resultado: porcentaje de error de palabras (WER). Más bajo = mejor.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import time
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


def dialect_candidates(pairs, min_count: int = 2) -> list[tuple[str, str, int]]:
    """Sustituciones de UNA palabra que se repiten entre lo transcrito y la corrección."""
    c: Counter = Counter()
    for ref, hyp in pairs:
        r, h = store.normalize(ref), store.normalize(hyp)
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=h, b=r, autojunk=False).get_opcodes():
            if op == "replace" and i2 - i1 == 1 and j2 - j1 == 1 and h[i1] != r[j1]:
                c[(h[i1], r[j1])] += 1
    return [(a, b, n) for (a, b), n in c.most_common() if n >= min_count]


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
    ap.add_argument("--engine", choices=("torch", "mlx", "mock"), default="torch", help="Motor para --model (mock = simulado)")
    ap.add_argument("--audio-ctx", choices=("full", "auto"), default="full",
                    help="Solo MLX: auto = contexto corto (más rápido, experimental)")
    ap.add_argument("--beam", type=int, default=1, help="Búsqueda amplia (1 = la más rápida)")
    ap.add_argument("--context", choices=("none", "confirmed"), default="none",
                    help="confirmed = dar como contexto la frase anterior (como en directo)")
    ap.add_argument("--gate-db", type=float, default=None,
                    help="Simular la puerta de volumen: frases más flojas cuentan como no transcritas")
    ap.add_argument("--sugerir-dialecto", action="store_true",
                    help="Proponer palabras de dialecto → alemán estándar a partir de las correcciones")
    ap.add_argument("--csv", help="Guardar el detalle frase a frase en este CSV")
    args = ap.parse_args()
    root = Path(args.data_dir)
    if args.model == "suizo":
        from asr import DEFAULT_MODEL
        args.model = DEFAULT_MODEL

    if args.sugerir_dialecto:
        pairs = [(seg["text"], seg["auto_text"]) for _s, _d, seg in done_segments(root, None)]
        cands = dialect_candidates(pairs)
        if not cands:
            print("Aún no hay sustituciones repetidas (hacen falta más frases corregidas).")
            return
        print("Whisper escribió → tú corregiste (veces). Revisa cada una: solo dialecto, no nombres:")
        for a, b, n in cands[:40]:
            print(f"  {a:>18} → {b:<18} ({n})")
        out = HERE / "vocab" / "dialecto-sugerencias.json"
        out.write_text(json.dumps({"note": "SUGERENCIAS sin revisar. Copia a dialecto-de.json solo las buenas.",
                                   "mappings": {a: b for a, b, _n in cands[:40]}},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nGuardadas en {out} (no se usan hasta que las copies a dialecto-de.json).")
        return

    live = [(s["id"], seg["text"], seg["auto_text"]) for s, _d, seg in done_segments(root, None)]
    report("ACIERTO EN DIRECTO (todas las sesiones corregidas)", live)
    test_live = [(s["id"], seg["text"], seg["auto_text"]) for s, _d, seg in done_segments(root, "test")]
    report("ACIERTO EN DIRECTO (solo sesiones de prueba)", test_live)

    rows = test_live
    if args.model:
        from asr import make_transcriber, should_drop  # carga el motor solo si hace falta
        from segmenter import level_db
        vocab = " ".join(Path(args.vocab).read_text(encoding="utf-8").split()) if args.vocab else ""
        tr = make_transcriber(args.engine, args.model, None, "de", vocab, args.audio_ctx, args.beam, args.context)
        rows = []
        segs = sorted(done_segments(root, "test"), key=lambda x: (x[0]["id"], x[2]["id"]))
        spent, gated, previous, last_sid = 0.0, 0, "", None
        for i, (s, d, seg) in enumerate(segs, 1):
            if s["id"] != last_sid:
                previous, last_sid = "", s["id"]          # el contexto no cruza de un culto a otro
            audio = read_wav(d / seg["file"])
            if args.gate_db is not None and level_db(audio) < args.gate_db:
                gated += 1
                hyp = ""
            else:
                t0 = time.monotonic()
                hyp = tr._run(audio, True, previous)
                spent += time.monotonic() - t0
                if should_drop(hyp, tr.prompt_text):
                    hyp = ""
            previous = hyp or previous
            rows.append((s["id"], seg["text"], hyp))
            print(f"\r  transcribiendo {i}/{len(segs)}…", end="", flush=True)
        print()
        extras = [x for x in (
            "contexto corto" if args.audio_ctx == "auto" else "",
            "vocab" if vocab else "",
            f"beam {args.beam}" if args.beam > 1 else "",
            "contexto frase anterior" if args.context == "confirmed" else "",
            f"puerta {args.gate_db:g} dB" if args.gate_db is not None else "") if x]
        report(f"MODELO {args.model} [{args.engine}{' · ' + ' · '.join(extras) if extras else ''}] "
               f"(sesiones de prueba)", rows)
        done = max(1, len(segs) - gated)
        print(f"  Tiempo medio por frase: {spent / done:.2f} s"
              + (f" · descartadas por la puerta de volumen: {gated}" if gated else ""))

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
