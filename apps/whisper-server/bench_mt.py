#!/usr/bin/env python3
"""
¿Cuánto tarda el Mac en traducir una frase a 1, 3, 5 y todos los idiomas con NLLB?

  python3 bench_mt.py                 # motor por defecto (CTranslate2, tras setup_nllb.sh)
  python3 bench_mt.py --comparar      # prueba varias combinaciones y dice cuál cumple
  python3 bench_mt.py --beams 1       # búsqueda más rápida
  python3 bench_mt.py --device mps    # tarjeta gráfica (experimental)
  python3 bench_mt.py --src es        # prédica en español (traduce al resto)

Objetivo del paso 4: con todos los idiomas, menos de 2 s por frase.
Muestra también algunas traducciones para que alguien que hable el idioma las revise.
"""
from __future__ import annotations

import argparse
import statistics
import time

import translate as T

OBJETIVO = 2.0

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

# Combinaciones para --comparar: (dispositivo, beams, núcleos)
COMBINACIONES = [
    ("cpu", 1, 4),     # la de por defecto (24.11.2026, M3: 1,89 s)
    ("cpu", 2, 4),
    ("cpu", 1, 8),
    ("cpu", 2, 8),
    ("mps", 1, 4),
    ("mps", 2, 4),
]


def medir(svc: T.TranslationService, frases: list[str], src: str, targets: list[str]):
    tiempos, salidas = [], []
    for f in frases:
        t1 = time.monotonic()
        salidas.append(svc.translate_sync(f, src, targets))
        tiempos.append(time.monotonic() - t1)
    return statistics.mean(tiempos), max(tiempos), salidas


def comparar(args, motor: str) -> None:
    frases = FRASES[args.src]
    todos = [c for c in T.LANGUAGES if c != args.src]
    print(f"Comparando {len(COMBINACIONES)} combinaciones · {len(frases)} frases · {len(todos)} idiomas\n")
    print(f"{'dispositivo':>11} | {'beams':>5} | {'núcleos':>7} | {'media':>7} | {'peor':>6} | resultado")
    print("-" * 66)
    filas = []
    for device, beams, threads in COMBINACIONES:
        try:
            t0 = time.monotonic()
            svc = T.TranslationService(T.load_backend(motor, beams=beams, threads=threads, device=device))
            carga = time.monotonic() - t0
            svc.translate_sync(frases[0], args.src, todos[:2])          # calentamiento
            media, peor, salidas = medir(svc, frases, args.src, todos)
        except Exception as exc:  # noqa: BLE001
            print(f"{device:>11} | {beams:>5} | {threads:>7} | no disponible: {str(exc)[:40]}")
            continue
        ok = "CUMPLE" if media < OBJETIVO else "no"
        print(f"{device:>11} | {beams:>5} | {threads:>7} | {media:>5.2f} s | {peor:>4.2f} s | {ok}"
              f"   (carga {carga:.1f} s)")
        filas.append(((device, beams, threads), media, salidas))
    if not filas:
        return
    base = filas[0]
    mejor = min(filas, key=lambda f: f[1])
    (device, beams, threads), media, salidas = mejor
    print(f"\nMás rápida: {device}, beams {beams}, {threads} núcleos → {media:.2f} s por frase")
    if mejor is not base:
        print("¿Cambia la calidad respecto a la actual? (solo las frases que salen distintas)")
        cambios = 0
        for f, a, b in zip(FRASES[args.src], base[2], salidas):
            for c in args.muestra.split(","):
                if a.get(c) != b.get(c):
                    cambios += 1
                    print(f"  {args.src}: {f}\n    {c} actual: {a.get(c)}\n    {c} rápida: {b.get(c)}")
        if not cambios:
            print("  Ninguna: mismas traducciones en " + args.muestra)
    flags = []
    if device != "cpu":
        flags.append(f"--mt-device {device}")
    if beams != 2:
        flags.append(f"--mt-beams {beams}")
    if threads != 4:
        flags.append(f"--mt-threads {threads}")
    if flags:
        print(f"\nPara usarla en directo:  npm start -- {' '.join(flags)}")
    if device == "mps":
        print("Ojo: en mps la traducción comparte la tarjeta gráfica con Whisper. Comprobar en un culto de "
              "prueba que Whisper no se vuelve más lento (report.py).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--motor", choices=("ct2", "transformers", "fake"), default="ct2")
    ap.add_argument("--beams", type=int, default=1)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    ap.add_argument("--comparar", action="store_true", help="Probar varias combinaciones y recomendar una")
    ap.add_argument("--src", default="de", choices=sorted(FRASES))
    ap.add_argument("--muestra", default="es,en,zh", help="Idiomas cuyas traducciones se muestran")
    args = ap.parse_args()

    if args.comparar:
        comparar(args, args.motor)
        return

    t0 = time.monotonic()
    backend = T.load_backend(args.motor, beams=args.beams, threads=args.threads, device=args.device)
    svc = T.TranslationService(backend)
    print(f"Motor: {backend.name} · beams {args.beams} · {args.threads} núcleos · "
          f"cargado en {time.monotonic() - t0:.1f} s")
    todos = [c for c in T.LANGUAGES if c != args.src]
    frases = FRASES[args.src]
    svc.translate_sync(frases[0], args.src, todos[:2])          # calentamiento

    print(f"\n{'Idiomas':>8} | {'media/frase':>11} | {'peor':>6} | {'por idioma':>10}")
    print("-" * 46)
    salidas = []
    for n in (1, 3, 5, len(todos)):
        media, peor, out = medir(svc, frases, args.src, todos[:n])
        if n == len(todos):
            salidas, media_todos = out, media
        print(f"{n:>8} | {media:>9.2f} s | {peor:>4.2f} s | {media / n:>8.2f} s")

    print("\nMuestra (para revisar con alguien que hable el idioma):")
    for f, out in list(zip(frases, salidas))[:4]:
        print(f"  {args.src}: {f}")
        for c in args.muestra.split(","):
            if c in out:
                print(f"    {c}: {out[c]}")
    veredicto = "CUMPLE" if media_todos < OBJETIVO else "NO cumple: prueba  npm run bench:mt -- --comparar"
    print(f"\nObjetivo del paso 4 ({len(todos)} idiomas < {OBJETIVO:g} s por frase): {media_todos:.2f} s → {veredicto}")
    print("Nota: con Whisper transcribiendo a la vez, la traducción irá algo más lenta.")


if __name__ == "__main__":
    main()
