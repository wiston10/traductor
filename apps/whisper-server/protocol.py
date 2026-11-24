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

  {"v":1,"type":"room","listeners":N,"langs":{"es":3,…}}     (cuántos móviles escuchan)

Página → servidor
  {"type":"config","save":bool,"src":"de-CH","targets":["es",…]}
  {"type":"flush"}
  (audio: mensajes binarios PCM int16, 16 kHz, mono)

Móvil del oyente  (/ws/oyente)
  móvil → servidor:
    {"type":"hello","pin":"1234"|"token":…,"device":…,"lang":"es","epoch":…,"since":N}
    {"type":"lang","lang":"en"}
  servidor → móvil:
    {"v":1,"type":"welcome","epoch":…,"lang":"es","src":"de","token":…,"state":"live|waiting"}
    {"v":1,"type":"line","seq":N,"text":…,"lang":"es","orig":…,"pending":bool}
        (la misma frase puede llegar dos veces: primero pendiente, luego traducida)
    {"v":1,"type":"reset","lang":"en"}      (cambió de idioma: se vuelve a llenar)
    {"v":1,"type":"state","state":"live|waiting"}
    {"v":1,"type":"error","code":"pin|wait|bad","text":…}
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


def room(listeners: int, langs: dict[str, int]) -> dict:
    return _msg("room", listeners=listeners, langs=langs)


def welcome(epoch: str, lang: str, src: str, token: str, state: str) -> dict:
    return _msg("welcome", epoch=epoch, lang=lang, src=src, token=token, state=state)


def line(seq: int, text: str, lang: str, orig: str = "", pending: bool = False) -> dict:
    m = _msg("line", seq=seq, text=text, lang=lang, orig=orig)
    if pending:
        m["pending"] = True
    return m


def reset(lang: str) -> dict:
    return _msg("reset", lang=lang)


def room_state(state: str) -> dict:
    return _msg("state", state=state)


def error(code: str, text: str) -> dict:
    return _msg("error", code=code, text=text)


def parse(raw: str) -> dict | None:
    """Mensaje de texto de la página → dict, o None si no es válido."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None
