"""
Formato de los mensajes entre el servidor y las páginas (versión 1).

Cada mensaje lleva "v" (versión). Las frases definitivas llevan "seq": un número que
crece de 1 en 1 por conexión, y su traducción llega después con el MISMO "seq".
Así la página sabe qué traducción va con qué frase, y más adelante (salas con oyentes)
un móvil que se reconecta podrá pedir «lo que me falta desde el número N».

Servidor → página
  {"v":1,"type":"status","text":…,"level":"live|warn"}
  {"v":1,"type":"partial","text":…}
  {"v":1,"type":"final","seq":N,"text":…}
  {"v":1,"type":"translation","seq":N,"tr":{"es":…,"en":…},"ms":…}
  {"v":1,"type":"config_ok","translate":["es",…],"engine":"nllb-ct2"|null}
  {"v":1,"type":"saved","count":…,"minutes":…,"session":…}
  {"v":1,"type":"flushed"}

Página → servidor
  {"type":"config","save":bool,"src":"de-CH","targets":["es",…]}
  {"type":"flush"}
  (audio: mensajes binarios PCM int16, 16 kHz, mono)
"""
from __future__ import annotations

import json

VERSION = 1


def _msg(kind: str, **fields) -> dict:
    return {"v": VERSION, "type": kind, **fields}


def status(text: str, level: str | None = None) -> dict:
    return _msg("status", text=text, **({"level": level} if level else {}))


def partial(text: str) -> dict:
    return _msg("partial", text=text)


def final(seq: int, text: str) -> dict:
    return _msg("final", seq=seq, text=text)


def translation(seq: int, tr: dict[str, str], seconds: float, error: str | None = None) -> dict:
    m = _msg("translation", seq=seq, tr=tr, ms=round(seconds * 1000))
    if error:
        m["error"] = error
    return m


def config_ok(targets: list[str], engine: str | None) -> dict:
    return _msg("config_ok", translate=targets, engine=engine)


def saved(count: int, seconds: float, session: str) -> dict:
    return _msg("saved", count=count, minutes=round(seconds / 60, 1), session=session)


def flushed() -> dict:
    return _msg("flushed")


def parse(raw: str) -> dict | None:
    """Mensaje de texto de la página → dict, o None si no es válido."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None
