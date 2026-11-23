"""
Almacén de frases para entrenamiento (sin dependencias externas).

Estructura en disco:
    training-data/
      2026-11-29_093012/            <- una carpeta por culto/sesión
        session.json                <- {"purpose": "train" | "test", "created": ..., "note": ...}
        segments.jsonl              <- una línea por frase
        000001.wav, 000002.wav…     <- audio 16 kHz mono

Cada línea de segments.jsonl:
    {"id": "000001", "file": "000001.wav", "duration": 4.2, "time": "...",
     "auto_text": "lo que escribió Whisper", "text": "texto corregido",
     "status": "pending" | "ok" | "corrected" | "discarded", "updated": "..."}
"""
from __future__ import annotations

import json
import os
import re
import threading
import wave
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
SESSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}$")
SEGMENT_RE = re.compile(r"^\d{6}$")
STATUSES = {"pending", "ok", "corrected", "discarded"}
PURPOSES = {"train", "test"}

_lock = threading.Lock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class Recorder:
    """Guarda las frases de UNA sesión en directo."""

    def __init__(self, root: Path):
        self.root = root
        self.dir: Path | None = None
        self.count = 0
        self.seconds = 0.0

    def _ensure_dir(self) -> Path:
        if self.dir is None:
            self.root.mkdir(parents=True, exist_ok=True)
            t = datetime.now().replace(microsecond=0)
            d = self.root / t.strftime("%Y-%m-%d_%H%M%S")
            while d.exists():                      # dos sesiones en el mismo segundo
                t = t + timedelta(seconds=1)
                d = self.root / t.strftime("%Y-%m-%d_%H%M%S")
            d.mkdir()
            _write_atomic(d / "session.json", json.dumps(
                {"purpose": "train", "created": _now(), "note": ""}, ensure_ascii=False))
            self.dir = d
        return self.dir

    def save(self, audio: np.ndarray, text: str) -> dict:
        d = self._ensure_dir()
        self.count += 1
        seg_id = f"{self.count:06d}"
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        with wave.open(str(d / f"{seg_id}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.tobytes())
        duration = round(len(pcm) / SAMPLE_RATE, 2)
        self.seconds += duration
        rec = {"id": seg_id, "file": f"{seg_id}.wav", "duration": duration, "time": _now(),
               "auto_text": text, "text": text, "status": "pending", "updated": None}
        with _lock, (d / "segments.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec


# ---------------------------------------------------------------------------
# Lectura y corrección (herramienta /corregir)
# ---------------------------------------------------------------------------
def _session_dir(root: Path, sid: str) -> Path:
    if not SESSION_RE.match(sid):
        raise ValueError("sesión no válida")
    d = root / sid
    if not d.is_dir():
        raise FileNotFoundError(sid)
    return d


def load_segments(d: Path) -> list[dict]:
    path = d / "segments.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def load_session_meta(d: Path) -> dict:
    try:
        meta = json.loads((d / "session.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        meta = {}
    meta.setdefault("purpose", "train")
    meta.setdefault("note", "")
    return meta


def summarize(d: Path) -> dict:
    segs = load_segments(d)
    done = [s for s in segs if s["status"] in ("ok", "corrected")]
    meta = load_session_meta(d)
    return {
        "id": d.name,
        "purpose": meta["purpose"],
        "note": meta["note"],
        "segments": len(segs),
        "pending": sum(s["status"] == "pending" for s in segs),
        "done": len(done),
        "discarded": sum(s["status"] == "discarded" for s in segs),
        "minutes_total": round(sum(s["duration"] for s in segs) / 60, 1),
        "minutes_done": round(sum(s["duration"] for s in done) / 60, 1),
    }


def list_sessions(root: Path) -> list[dict]:
    if not root.is_dir():
        return []
    dirs = sorted((p for p in root.iterdir() if p.is_dir() and SESSION_RE.match(p.name)), reverse=True)
    return [summarize(d) for d in dirs]


def get_session(root: Path, sid: str) -> dict:
    d = _session_dir(root, sid)
    return {**summarize(d), "items": load_segments(d)}


def update_segment(root: Path, sid: str, seg_id: str, text: str | None, status: str) -> dict:
    if not SEGMENT_RE.match(seg_id):
        raise ValueError("frase no válida")
    if status not in STATUSES:
        raise ValueError("estado no válido")
    d = _session_dir(root, sid)
    with _lock:
        segs = load_segments(d)
        for s in segs:
            if s["id"] == seg_id:
                if text is not None:
                    s["text"] = " ".join(text.split())
                s["status"] = status
                s["updated"] = _now()
                found = s
                break
        else:
            raise FileNotFoundError(seg_id)
        _write_atomic(d / "segments.jsonl", "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in segs))
    return found


def set_session_meta(root: Path, sid: str, purpose: str | None = None, note: str | None = None) -> dict:
    d = _session_dir(root, sid)
    with _lock:
        meta = load_session_meta(d)
        if purpose is not None:
            if purpose not in PURPOSES:
                raise ValueError("uso no válido")
            meta["purpose"] = purpose
        if note is not None:
            meta["note"] = note.strip()[:200]
        _write_atomic(d / "session.json", json.dumps(meta, ensure_ascii=False))
    return meta


# ---------------------------------------------------------------------------
# Medición: porcentaje de error de palabras (WER)
# ---------------------------------------------------------------------------
_PUNCT = re.compile(r"[^\w\s'-]", re.UNICODE)


def normalize(text: str) -> list[str]:
    """Minúsculas, sin puntuación, ß=ss (así escriben en Suiza)."""
    t = _PUNCT.sub(" ", text.lower().replace("ß", "ss"))
    return t.split()


def word_errors(ref: str, hyp: str) -> tuple[int, int]:
    """(errores, palabras de referencia) con distancia de edición por palabras."""
    r, h = normalize(ref), normalize(hyp)
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hw in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw))
        prev = cur
    return prev[-1], len(r)


def wer(pairs: list[tuple[str, str]]) -> float:
    errors = words = 0
    for ref, hyp in pairs:
        e, n = word_errors(ref, hyp)
        errors += e
        words += n
    return errors / words if words else 0.0
