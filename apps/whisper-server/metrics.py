"""
Registro automático de rendimiento (para el culto de prueba y en general).

El servidor anota cada paso de Whisper y cada idea en  metrics/AAAA-MM-DD_HHMMSS.jsonl
(una línea JSON por evento; no va a git). Después:  python3 report.py  lo resume.

Eventos:
  {"t": 12.3, "ev": "whisper", "kind": "partial"|"final", "audio_s": 4.1, "took_s": 0.82}
  {"t": 15.0, "ev": "idea", "ms": 4210, "result": "ok"|"empty"|"paused"|"error"|"busy"}
  {"t": 0.0,  "ev": "start", "model": "...", "idea_model": "...", "device": "..."}
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path


class Metrics:
    def __init__(self, folder: Path, enabled: bool = True):
        self.enabled = enabled
        self.t0 = time.monotonic()
        self.path: Path | None = None
        self._lock = threading.Lock()
        # Carga reciente de Whisper (media móvil del tiempo por paso, en s) y cuándo se midió
        self.whisper_cost = 0.0
        self.whisper_cost_at = 0.0
        if enabled:
            folder.mkdir(parents=True, exist_ok=True)
            self.path = folder / f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.jsonl"

    def log(self, ev: str, **data) -> None:
        if not self.enabled or self.path is None:
            return
        rec = {"t": round(time.monotonic() - self.t0, 2), "ev": ev, **data}
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line)

    def whisper_step(self, kind: str, audio_s: float, took_s: float) -> None:
        now = time.monotonic()
        # Si hace rato que no había pasos (silencio), empezar de cero
        if now - self.whisper_cost_at > 30:
            self.whisper_cost = took_s
        else:
            self.whisper_cost = 0.7 * self.whisper_cost + 0.3 * took_s
        self.whisper_cost_at = now
        self.log("whisper", kind=kind, audio_s=round(audio_s, 2), took_s=round(took_s, 3))

    def whisper_overloaded(self, threshold_s: float) -> bool:
        """¿Whisper va lento AHORA? (medición de los últimos 20 s)"""
        return (time.monotonic() - self.whisper_cost_at) < 20 and self.whisper_cost > threshold_s
