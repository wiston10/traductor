#!/usr/bin/env python3
"""
Compara motores de Whisper en ESTE Mac con el MISMO audio: cuánto tarda cada frase y qué escribe.

  .venv/bin/python bench_asr.py                      # usa frases guardadas en training-data/
  .venv/bin/python bench_asr.py --audio predica.wav  # o cualquier grabación WAV

Para convertir una grabación (p. ej. de QuickTime, .m4a) a WAV en Mac:
  afconvert -f WAVE -d LEI16@16000 -c 1 grabacion.m4a predica.wav

Prueba por defecto (las que estén disponibles):
  torch + modelo suizo   (lo que usáis ahora)
  mlx   + turbo normal   (sin conversión)
  mlx   + modelo suizo   (si ya ejecutaste tools/convert_to_mlx.sh)
"""
from __future__ import annotations

import argparse
import gc
import statistics
import time
import wave
from pathlib import Path

import numpy as np

import server as S

HERE = Path(__file__).resolve().parent
SR = S.SAMPLE_RATE


def read_wav(path: Path) -> np.ndarray:
    """WAV de cualquier frecuencia/canales -> mono 16 kHz float32."""
    with wave.open(str(path)) as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise SystemExit(f"{path.name}: usa WAV de 16 bits (afconvert -d LEI16@16000).")
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if sr != SR:                                   # remuestreo simple (suficiente para comparar)
        n = int(len(a) * SR / sr)
        a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)
    return a


def clips_from_training(limit: int) -> list[np.ndarray]:
    root = HERE / "training-data"
    out = []
    for d in sorted(root.glob("*/"), reverse=True) if root.exists() else []:
        for f in sorted(d.glob("*.wav")):
            out.append(read_wav(f))
            if len(out) >= limit:
                return out
    return out


def clips_from_file(path: Path, seconds: float, limit: int) -> list[np.ndarray]:
    a = read_wav(path)
    step = int(seconds * SR)
    return [a[i:i + step] for i in range(0, len(a) - SR, step)][:limit]


def free(tr) -> None:
    del tr
    gc.collect()
    try:
        import torch
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--audio", type=Path, help="Grabación WAV para la prueba")
    ap.add_argument("--clips", type=int, default=12, help="Cuántas frases/trozos probar")
    ap.add_argument("--seconds", type=float, default=5.0, help="Duración de cada trozo (con --audio)")
    ap.add_argument("--only", choices=("torch", "mlx-turbo", "mlx-swiss"), action="append",
                    help="Probar solo estos motores (repetible)")
    args = ap.parse_args()

    clips = clips_from_file(args.audio, args.seconds, args.clips) if args.audio else clips_from_training(args.clips)
    if not clips:
        raise SystemExit("No hay audio para probar. Usa --audio grabacion.wav, o guarda frases con "
                         "«💾 Guardar para entrenamiento» en el apuntador.")
    print(f"{len(clips)} trozos de audio ({sum(len(c) for c in clips) / SR:.0f} s en total)\n")

    configs = [("torch", "torch", S.DEFAULT_MODEL), ("mlx-turbo", "mlx", "turbo")]
    if (S.MLX_SWISS_PATH / "config.json").exists():
        configs.append(("mlx-swiss", "mlx", S.DEFAULT_MODEL))
    else:
        print("(mlx-swiss no disponible: ejecuta  bash tools/convert_to_mlx.sh  para incluirlo)\n")
    if args.only:
        configs = [c for c in configs if c[0] in args.only]

    results: dict[str, list[tuple[float, str]]] = {}
    for name, engine, model in configs:
        print(f"→ {name}: cargando…", flush=True)
        try:
            tr = S.make_transcriber(engine, model, None, "de")
        except SystemExit as exc:
            print(f"   ✕ {exc}\n")
            continue
        rows = []
        for c in clips:
            t0 = time.monotonic()
            text = tr._run(c)
            rows.append((time.monotonic() - t0, text))
        results[name] = rows
        t = [r[0] for r in rows]
        print(f"   típico {statistics.median(t):.2f} s por trozo (peor {max(t):.2f} s)\n")
        free(tr)

    if not results:
        return
    names = list(results)
    print("=" * 72)
    for i in range(len(clips)):
        print(f"\nTrozo {i + 1} ({len(clips[i]) / SR:.1f} s)")
        for n in names:
            secs, text = results[n][i]
            print(f"  {n:<10} {secs:5.2f} s  {text}")
    print("\n" + "=" * 72)
    base = statistics.median(r[0] for r in results[names[0]])
    for n in names:
        med = statistics.median(r[0] for r in results[n])
        speed = ""
        if n != names[0] and med > 0:
            r = base / med
            speed = (f"  ({r:.1f}× más rápido que {names[0]})" if r >= 1.05 else
                     f"  ({1 / r:.1f}× más lento que {names[0]})" if r <= 0.95 else f"  (igual que {names[0]})")
        print(f"{n:<10} típico {med:.2f} s por trozo{speed}")
    print("\nCompara también los TEXTOS: más rápido solo sirve si acierta igual.")
    print("Para medir el acierto con frases corregidas:  .venv/bin/python evaluate.py --engine mlx --model <modelo>")


if __name__ == "__main__":
    main()
