#!/usr/bin/env python3
"""
¿Cuánto tarda el Mac en traducir una frase a 1, 3, 5 y 15 idiomas con NLLB?

  python3 bench_mt.py                 # motor por defecto (CTranslate2, tras setup_nllb.sh)
  python3 bench_mt.py --motor transformers
  python3 bench_mt.py --beams 1       # búsqueda más rápida
  python3 bench_mt.py --src es        # prédica en español (traduce al resto)

Objetivo del paso 4: con los 15 idiomas, menos de 2 s por frase.
Muestra también algunas traducciones para que alguien que hable el idioma las revise.
"""
from __future__ import annotations

import argparse
import statistics
import time

import translate as T

FRASES = {
    "de": [
        "Gott hat uns nicht einen Geist der Furcht gegeben.",
        "Heute lesen wir aus dem zweiten Brief an Timotheus.",
        "Viele Menschen glauben, sie müssten zuerst ihr Leben in Ordnung bringen.",
        "Aber Jesus sagt: Komm so, wie du bist.",
        "Die Gnade Gottes ist größer als unsere Schuld.",
        "Wir feiern heute zusammen das Abendmahl.",
        "Betet füreinander, besonders in schweren Zeiten.",
        "Amen.",
    ],
    "es": [
        "Dios no nos ha dado un espíritu de temor.",
        "Hoy leemos de la segunda carta a Timoteo.",
        "Mucha gente cree que primero debe ordenar su vida.",
        "Pero Jesús dice: ven tal como eres.",
    ],
    "en": [
        "God has not given us a spirit of fear.",
        "Today we read from the second letter to Timothy.",
        "Many people believe they must first put their life in order.",
        "But Jesus says: come as you are.",
    ],
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--motor", choices=("ct2", "transformers"), default="ct2")
    ap.add_argument("--beams", type=int, default=2)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--src", default="de", choices=sorted(FRASES))
    ap.add_argument("--muestra", default="es,en,zh", help="Idiomas cuyas traducciones se muestran")
    args = ap.parse_args()

    t0 = time.monotonic()
    backend = T.load_backend(args.motor, beams=args.beams, threads=args.threads)
    svc = T.TranslationService(backend)
    print(f"Motor: {backend.name} · beams {args.beams} · {args.threads} núcleos · "
          f"cargado en {time.monotonic() - t0:.1f} s")
    todos = [c for c in T.LANGUAGES if c != args.src]
    frases = FRASES[args.src]
    svc.translate_sync(frases[0], args.src, todos[:2])          # calentamiento

    print(f"\n{'Idiomas':>8} | {'media/frase':>11} | {'peor':>6} | {'por idioma':>10}")
    print("-" * 46)
    resultados = {}
    for n in (1, 3, 5, len(todos)):
        tiempos = []
        for f in frases:
            t1 = time.monotonic()
            out = svc.translate_sync(f, args.src, todos[:n])
            tiempos.append(time.monotonic() - t1)
            if n == len(todos):
                resultados[f] = out
        media = statistics.mean(tiempos)
        print(f"{n:>8} | {media:>9.2f} s | {max(tiempos):>4.2f} s | {media / n:>8.2f} s")

    print("\nMuestra (para revisar con alguien que hable el idioma):")
    for f, out in list(resultados.items())[:4]:
        print(f"  {args.src}: {f}")
        for c in args.muestra.split(","):
            if c in out:
                print(f"    {c}: {out[c]}")
    tiempos15 = []
    for f in frases:
        t1 = time.monotonic()
        svc.translate_sync(f, args.src, todos)
        tiempos15.append(time.monotonic() - t1)
    media15 = statistics.mean(tiempos15)
    veredicto = "CUMPLE" if media15 < 2.0 else "NO cumple (probar --beams 1, o traducir solo idiomas con oyentes)"
    print(f"\nObjetivo del paso 4 (15 idiomas < 2 s por frase): {media15:.2f} s → {veredicto}")
    print("Nota: con Whisper transcribiendo a la vez, la traducción irá algo más lenta. "
          "NLLB usa el procesador; Whisper, la tarjeta gráfica.")


if __name__ == "__main__":
    main()
