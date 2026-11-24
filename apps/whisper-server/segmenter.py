"""
Corte del audio en directo en frases.

Sin dependencias pesadas (solo numpy): se prueba sin el modelo.
"""
from __future__ import annotations

import math

import numpy as np

SAMPLE_RATE = 16000
FRAME = 480  # 30 ms


def level_db(audio: np.ndarray) -> float:
    """Nivel (dBFS) de las partes con voz: media de la energía del 30 % de tramos más fuertes."""
    n = len(audio) // FRAME
    if n == 0:
        return -120.0
    frames = audio[: n * FRAME].reshape(n, FRAME)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    top = np.sort(rms)[-max(1, int(n * 0.3)):]
    return 20 * math.log10(float(top.mean()) + 1e-12)


class Segmenter:
    """
    Acumula audio y decide cuándo transcribir:
      - cada `partial_every` s: texto provisional del segmento actual (0 = desactivado)
      - tras `silence` s de pausa: cierra la frase (texto definitivo)
      - si nadie hace pausa (predicador rápido): corta como máximo a `max_seg` s,
        en el punto más silencioso de los últimos segundos, para no partir palabras.
      - puerta de volumen (`gate_db`): una «frase» más floja que eso no se manda al modelo
        (ruido de la sala, música de fondo muy baja). Ahorra trabajo y evita textos inventados.
    """

    def __init__(self, partial_every: float, silence: float, max_seg: float, gate_db: float | None = None):
        self.partial_every = partial_every
        self.silence = silence
        self.max_seg = max_seg
        self.gate_db = gate_db
        self.gated = 0           # frases descartadas por la puerta de volumen
        self.buf = np.zeros(0, dtype=np.float32)
        self.noise = 0.004       # nivel de ruido de fondo (se adapta)
        self.last_partial = 0.0
        self.last_partial_text = ""
        self.last_partial_len = 0
        self.step_cost = 0.0     # cuánto tardó el último paso (s)

    def note_cost(self, seconds: float) -> None:
        # media móvil del tiempo de inferencia
        self.step_cost = seconds if self.step_cost == 0 else 0.7 * self.step_cost + 0.3 * seconds

    def add(self, pcm: bytes) -> None:
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        self.buf = np.concatenate([self.buf, samples])

    @property
    def seconds(self) -> float:
        return len(self.buf) / SAMPLE_RATE

    def _frame_rms(self) -> np.ndarray:
        n = len(self.buf) // FRAME
        if n == 0:
            return np.zeros(0)
        frames = self.buf[: n * FRAME].reshape(n, FRAME)
        return np.sqrt((frames ** 2).mean(axis=1) + 1e-12)

    def _passes_gate(self, audio: np.ndarray) -> bool:
        if self.gate_db is None or level_db(audio) >= self.gate_db:
            return True
        self.gated += 1
        return False

    def decide(self, now: float):
        """Devuelve ("final", audio) | ("partial", audio) | (None, None)."""
        rms = self._frame_rms()
        if len(rms) == 0:
            return None, None
        # Ruido de fondo adaptativo: percentil bajo de la energía reciente
        self.noise = 0.95 * self.noise + 0.05 * float(np.percentile(rms[-100:], 10))
        # Suelo bajo: el audio de una pestaña con el volumen del vídeo bajado llega flojo
        threshold = max(0.003, self.noise * 3.0)
        speech = rms > threshold

        if not speech.any():
            # Solo silencio: no acumular indefinidamente
            if self.seconds > 2.0:
                self.buf = self.buf[-int(0.3 * SAMPLE_RATE):]
            return None, None

        # Silencio al final
        trailing = 0
        for v in speech[::-1]:
            if v:
                break
            trailing += 1
        trailing_s = trailing * FRAME / SAMPLE_RATE

        if trailing_s >= self.silence:
            audio = self._cut(len(self.buf))
            # Menos de 0,25 s de voz (tos, golpe, ruido): Whisper solo "inventaría" texto
            if speech.sum() * FRAME / SAMPLE_RATE < 0.25 or not self._passes_gate(audio):
                return None, None
            return "final", audio

        if self.seconds >= self.max_seg:
            # Cortar en el marco más silencioso de los últimos 2 s
            window = int(2.0 * SAMPLE_RATE / FRAME)
            start = max(0, len(rms) - window)
            cut_frame = start + int(np.argmin(rms[start:]))
            audio = self._cut(max(cut_frame, 1) * FRAME)
            return ("final", audio) if self._passes_gate(audio) else (None, None)

        # Intervalo adaptativo: nunca pedir parciales más rápido de lo que el Mac
        # puede procesarlos (deja hueco para que los finales no esperen).
        if self.partial_every <= 0:          # texto provisional desactivado: solo frases definitivas
            return None, None
        # Si ya empieza una pausa, la frase definitiva es inminente: un paso provisional
        # ahora solo la retrasaría (el modelo hace una cosa a la vez).
        if trailing_s >= 0.2:
            return None, None
        interval = max(self.partial_every, self.step_cost * 1.5)
        grown = len(self.buf) - self.last_partial_len >= int(0.4 * SAMPLE_RATE)
        if now - self.last_partial >= interval and self.seconds >= 0.6 and grown:
            self.last_partial = now
            self.last_partial_len = len(self.buf)
            return "partial", self.buf.copy()

        return None, None

    def flush(self) -> np.ndarray | None:
        """Entrega todo lo pendiente (si tiene algo de voz) y vacía el búfer."""
        rms = self._frame_rms()
        has_speech = len(rms) and (rms > max(0.003, self.noise * 3.0)).sum() * FRAME / SAMPLE_RATE >= 0.25
        audio = self._cut(len(self.buf))
        return audio if has_speech and self._passes_gate(audio) else None

    def _cut(self, n: int) -> np.ndarray:
        audio, self.buf = self.buf[:n], self.buf[n:]
        self.last_partial = 0.0
        self.last_partial_len = 0
        self.last_partial_text = ""
        return audio
