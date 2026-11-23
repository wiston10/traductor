#!/usr/bin/env python3
"""
Compara motores de Whisper en ESTE Mac con el MISMO audio: cuánto tarda cada frase y qué escribe.

  npm run bench                                       # sin preparar nada (ver abajo)
  .venv/bin/python bench_asr.py --audio grabacion.m4a # con una grabación propia (cualquier formato)

Audio que usa, por orden:
  1. --audio <archivo>  (WAV, M4A, MP3… se convierte solo)
  2. frases guardadas con «💾 Guardar para entrenamiento» (training-data/)
  3. si no hay nada: frases de prédica en alemán leídas por la voz del Mac (comando «say»).
     Sirve para medir la VELOCIDAD; para el acierto con suizo alemán hace falta audio real.

Prueba por defecto (las que estén disponibles):
  torch + modelo suizo   (lo que usáis ahora)
  mlx   + turbo normal   (sin conversión)
  mlx   + modelo suizo   (si ya ejecutaste tools/convert_to_mlx.sh)
"""
from __future__ import annotations

import argparse
import gc
import importlib.util
import re
import shutil
import statistics
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import logging
import os
import warnings

import numpy as np

os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")    # sin avisos técnicos de transformers
warnings.filterwarnings("ignore")
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

import server as S  # noqa: E402

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


def to_wav(path: Path) -> Path:
    """Cualquier formato que entienda macOS -> WAV 16 kHz mono (con afconvert, incluido en macOS)."""
    if not path.exists():
        raise SystemExit(f"No encuentro el archivo «{path}». Comprueba el nombre y la carpeta "
                         f"(ahora estás en {Path.cwd()}), o ejecuta sin --audio.")
    if path.suffix.lower() == ".wav":
        return path
    if not shutil.which("afconvert"):
        raise SystemExit("Para archivos que no son WAV hace falta macOS (afconvert).")
    out = Path(tempfile.mkdtemp()) / (path.stem + ".wav")
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(path), str(out)],
                   check=True, capture_output=True)
    return out


FRASES = [
    "Liebe Gemeinde, schön, dass ihr heute Morgen alle da seid.",
    "Wir lesen heute aus dem Johannesevangelium, Kapitel drei, Vers sechzehn.",
    "Denn so sehr hat Gott die Welt geliebt, dass er seinen einzigen Sohn gab.",
    "Und das heisst für uns ganz konkret: Wir müssen uns diese Liebe nicht verdienen.",
    "Viele von uns denken, sie müssten zuerst perfekt sein, bevor Gott sie annimmt.",
    "Aber Paulus schreibt im Römerbrief, dass wir aus Gnade gerettet sind, nicht aus Werken.",
    "Das ist die gute Nachricht, das Evangelium, das wir heute feiern dürfen.",
    "Lasst uns gemeinsam beten.",
]


def german_voice() -> str | None:
    """Una voz alemana instalada en el Mac (preferible de Suiza)."""
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    voices = []
    for line in out.splitlines():
        m = re.match(r"^(.+?)\s+([a-z]{2}_[A-Z]{2})\s+#", line)
        if m and m.group(2).startswith("de_"):
            voices.append((m.group(2) != "de_CH", m.group(1).strip()))
    return sorted(voices)[0][1] if voices else None


def clips_from_say() -> list[np.ndarray]:
    if not (shutil.which("say") and shutil.which("afconvert")):
        return []
    voice = german_voice()
    print(f"Generando frases de prueba con la voz del Mac ({voice or 'voz por defecto'})…")
    tmp = Path(tempfile.mkdtemp())
    clips = []
    for i, frase in enumerate(FRASES):
        aiff, wav = tmp / f"{i}.aiff", tmp / f"{i}.wav"
        cmd = ["say", "-o", str(aiff)] + (["-v", voice] if voice else []) + [frase]
        subprocess.run(cmd, check=True, capture_output=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff), str(wav)],
                       check=True, capture_output=True)
        clips.append(read_wav(wav))
    print("(Voz sintética en alemán estándar: vale para medir VELOCIDAD, no el acierto con suizo alemán.)\n")
    return clips


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
    a = read_wav(to_wav(path))
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
    ap.add_argument("--only", choices=("torch", "mlx-turbo", "turbo-corto", "mlx-swiss", "swiss-corto"),
                    action="append",
                    help="Probar solo estos motores (repetible)")
    args = ap.parse_args()

    if args.audio:
        clips = clips_from_file(args.audio, args.seconds, args.clips)
    else:
        clips = clips_from_training(args.clips) or clips_from_say()
    if not clips:
        raise SystemExit("No hay audio para probar. Usa --audio grabacion.m4a, o guarda frases con "
                         "«💾 Guardar para entrenamiento» en el apuntador.")
    print(f"{len(clips)} trozos de audio ({sum(len(c) for c in clips) / SR:.0f} s en total)\n")

    # (nombre, motor, modelo, contexto de audio)
    configs = [("torch", "torch", S.DEFAULT_MODEL, "full")]
    if importlib.util.find_spec("mlx_whisper") is None:
        print("MLX no está instalado: solo se prueba el motor actual.\n"
              "  Para instalarlo y convertir el modelo suizo (una vez):  bash tools/convert_to_mlx.sh\n")
    else:
        configs += [("mlx-turbo", "mlx", "turbo", "full"), ("turbo-corto", "mlx", "turbo", "auto")]
        if (S.MLX_SWISS_PATH / "config.json").exists():
            configs += [("mlx-swiss", "mlx", S.DEFAULT_MODEL, "full"),
                        ("swiss-corto", "mlx", S.DEFAULT_MODEL, "auto")]
        else:
            print("(mlx-swiss no disponible: ejecuta  bash tools/convert_to_mlx.sh  para incluirlo)\n")
    if args.only:
        configs = [c for c in configs if c[0] in args.only]

    results: dict[str, list[tuple[float, str]]] = {}
    for name, engine, model, ctx in configs:
        print(f"→ {name}: cargando…", flush=True)
        try:
            tr = S.make_transcriber(engine, model, None, "de", "", ctx)
        except SystemExit as exc:
            print(f"   ✕ {exc}\n")
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"   ✕ No se pudo cargar {name}: {exc}\n")
            continue
        rows = []
        for c in clips:
            t0 = time.monotonic()
            text = tr._run(c)
            rows.append((time.monotonic() - t0, text))
        results[name] = rows
        t = [r[0] for r in rows]
        extra = f", repetidas con contexto completo: {tr.fallbacks}" if getattr(tr, "short", False) else ""
        print(f"   típico {statistics.median(t):.2f} s por trozo (peor {max(t):.2f} s){extra}\n")
        free(tr)

    if not results:
        return
    names = list(results)
    print("=" * 72)
    for i in range(len(clips)):
        print(f"\nTrozo {i + 1} ({len(clips[i]) / SR:.1f} s)")
        for n in names:
            secs, text = results[n][i]
            print(f"  {n:<12} {secs:5.2f} s  {text}")
    print("\n" + "=" * 72)
    base = statistics.median(r[0] for r in results[names[0]])
    for n in names:
        med = statistics.median(r[0] for r in results[n])
        speed = ""
        if n != names[0] and med > 0:
            r = base / med
            speed = (f"  ({r:.1f}× más rápido que {names[0]})" if r >= 1.05 else
                     f"  ({1 / r:.1f}× más lento que {names[0]})" if r <= 0.95 else f"  (igual que {names[0]})")
        print(f"{n:<12} típico {med:.2f} s por trozo{speed}")
    print("\nCompara también los TEXTOS: más rápido solo sirve si acierta igual.")
    print("Para medir el acierto con frases corregidas:  .venv/bin/python evaluate.py --engine mlx --model <modelo>")


if __name__ == "__main__":
    main()
