#!/usr/bin/env python3
"""
Informe de rendimiento de una sesión (p. ej. el culto de prueba).

  .venv/bin/python report.py              # la sesión más reciente de metrics/
  .venv/bin/python report.py metrics/2026-11-29_093012.jsonl

Responde a: ¿Whisper fue rápido todo el culto o se ralentizó al calentarse el Mac?
¿Cuánto tardaron las ideas? ¿Cuántas veces se pausaron para proteger la transcripción?
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLOW_S = 2.5          # un paso de Whisper por encima de esto se nota como retraso
TRAMO_MIN = 10


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    return v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))]


def load(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def main() -> None:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        files = sorted((HERE / "metrics").glob("*.jsonl"))
        if not files:
            print("No hay registros en metrics/. Arranca el servidor y usa el apuntador primero.")
            return
        path = files[-1]
    events = load(path)
    whisper = [e for e in events if e.get("ev") == "whisper"]
    ideas = [e for e in events if e.get("ev") == "idea"]
    start = next((e for e in events if e.get("ev") == "start"), {})
    if not whisper and not ideas:
        print(f"{path.name}: la sesión no tiene datos (¿se llegó a pulsar «Empezar»?).")
        return

    dur = max(e["t"] for e in events) / 60
    print(f"Sesión {path.stem} · {dur:.0f} min · modelo de ideas: {start.get('idea_model', '?')}\n")

    print(f"{'Tramo':<12}{'Whisper típico':>15}{'peor (p90)':>12}{'pasos lentos':>14}"
          f"{'Ideas':>8}{'idea típica':>13}{'pausas':>8}")
    tramos = int(dur // TRAMO_MIN) + 1
    firsts, lasts = [], []
    for i in range(tramos):
        a, b = i * TRAMO_MIN * 60, (i + 1) * TRAMO_MIN * 60
        w = [e["took_s"] for e in whisper if a <= e["t"] < b]
        ok = [e["ms"] / 1000 for e in ideas if a <= e["t"] < b and e.get("result") == "ok"]
        paused = sum(1 for e in ideas if a <= e["t"] < b and e.get("result") == "paused")
        if not w and not ok and not paused:
            continue
        slow = sum(1 for x in w if x > SLOW_S)
        if not firsts:
            firsts = w
        lasts = w or lasts
        print(f"{f'{i * TRAMO_MIN}-{(i + 1) * TRAMO_MIN} min':<12}"
              f"{(f'{statistics.median(w):.2f} s' if w else '—'):>15}"
              f"{(f'{pct(w, 90):.2f} s' if w else '—'):>12}"
              f"{(f'{100 * slow / len(w):.0f} %' if w else '—'):>14}"
              f"{len(ok):>8}"
              f"{(f'{statistics.median(ok):.1f} s' if ok else '—'):>13}"
              f"{paused:>8}")

    all_w = [e["took_s"] for e in whisper]
    ok_all = [e["ms"] / 1000 for e in ideas if e.get("result") == "ok"]
    counts = {r: sum(1 for e in ideas if e.get("result") == r) for r in ("ok", "empty", "paused", "error", "busy")}
    print("\nConclusiones:")
    if all_w:
        slow_pct = 100 * sum(1 for x in all_w if x > SLOW_S) / len(all_w)
        verdict = "bien" if slow_pct < 5 else "justo" if slow_pct < 20 else "lento: el Mac no da abasto"
        print(f"  · Whisper: {statistics.median(all_w):.2f} s por paso, {slow_pct:.0f} % de pasos lentos → {verdict}.")
        if firsts and lasts and statistics.median(lasts) > 1.4 * statistics.median(firsts):
            print(f"  · Se ralentizó con el tiempo ({statistics.median(firsts):.2f} s → {statistics.median(lasts):.2f} s): "
                  "probablemente el Mac se calentó. Prueba con el Mac sobre una superficie fresca, "
                  "enchufado, o sin modo idea.")
    if ideas:
        if ok_all:
            print(f"  · Ideas: {counts['ok']} mostradas, típico {statistics.median(ok_all):.1f} s "
                  f"(peor {pct(ok_all, 90):.1f} s).")
        print(f"  · Sin contenido: {counts['empty']} · en pausa para proteger la transcripción: {counts['paused']} · "
              f"errores: {counts['error']}.")
        if counts["paused"] > 0.2 * max(1, len(ideas)):
            print("  · Muchas pausas: el modo idea compite demasiado con Whisper en este Mac.")
    else:
        print("  · El modo idea no se usó en esta sesión.")


if __name__ == "__main__":
    main()
