"""
La sala del culto: reparte cada frase a los móviles, cada uno en su idioma.

  - El operador (la página del Mac) manda el audio; el servidor numera cada frase (seq).
  - Cada oyente elige su idioma. Solo se traducen los idiomas que alguien escucha.
  - Se guardan las últimas frases: un móvil que se reconecta recibe lo que se perdió.
  - Un solo socket por móvil: si el mismo móvil se conecta otra vez, se cierra el anterior.
  - Entrada con PIN (el QR lo lleva dentro). Después, el móvil guarda un pase firmado
    con un secreto propio del servidor (no con el PIN), válido unas horas.

Sin dependencias de red: se prueba con funciones de envío falsas.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

import protocol as P
from translate import ALL_LANGUAGES, TranslationService, clean_targets, short_code

log = logging.getLogger("whisper-server")

Send = Callable[[dict], Awaitable[None]]
HISTORY = 300            # frases guardadas para reconexiones
REPLAY_NEW = 6           # al entrar por primera vez: las últimas N frases, para tener contexto
TOKEN_HOURS = 6
PIN_TRIES = 8            # intentos de PIN fallidos por dirección cada 5 minutos


def load_secret(path: Path) -> bytes:
    """Secreto del servidor para firmar los pases (se crea una vez; no va a git)."""
    try:
        data = path.read_bytes()
        if len(data) >= 32:
            return data
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    data = secrets.token_bytes(32)
    path.write_bytes(data)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return data


@dataclass
class Line:
    seq: int
    text: str                     # en el idioma de la prédica
    t: float                      # cuándo terminó la frase (para medir el retraso)
    tr: dict[str, str] = field(default_factory=dict)


@dataclass
class Listener:
    device: str
    lang: str
    send: Send
    close: Callable[[], Awaitable[None]] | None = None


class Room:
    def __init__(self, src: str, pin: str | None = None, secret: bytes | None = None,
                 translator: TranslationService | None = None, history: int = HISTORY):
        self.src = short_code(src)
        self.pin = pin or f"{secrets.randbelow(10000):04d}"
        self.epoch = uuid.uuid4().hex[:12]        # identifica esta sala (este arranque)
        self.secret = secret or secrets.token_bytes(32)
        self.translator = translator
        self.lines: deque[Line] = deque(maxlen=history)
        self.seq = 0
        self.listeners: dict[str, Listener] = {}
        self.operator: Send | None = None
        self.operator_langs: list[str] = []
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self.pending = 0                          # traducciones encargadas y aún sin enviar
        self.on_latency: Callable[[float, int], None] | None = None
        self._fails: dict[str, list[float]] = {}
        self._worker: asyncio.Task | None = None

    # ------------------------------------------------------------------ acceso
    def _pin_tag(self) -> str:
        return hashlib.sha256(self.pin.encode()).hexdigest()[:8]

    def make_token(self, now: float | None = None) -> str:
        exp = int((now or time.time()) + TOKEN_HOURS * 3600)
        body = f"{exp}.{self._pin_tag()}"
        sig = hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()[:32]
        return f"{body}.{sig}"

    def token_ok(self, token: str, now: float | None = None) -> bool:
        try:
            exp, tag, sig = str(token).split(".")
            body = f"{exp}.{tag}"
            good = hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()[:32]
            return hmac.compare_digest(sig, good) and tag == self._pin_tag() and int(exp) > (now or time.time())
        except (ValueError, AttributeError):
            return False

    def check_pin(self, pin: str, who: str, now: float | None = None) -> bool | None:
        """True = correcto · False = incorrecto · None = demasiados intentos (esperar)."""
        now = now or time.time()
        fails = [t for t in self._fails.get(who, []) if now - t < 300]
        if len(fails) >= PIN_TRIES:
            self._fails[who] = fails
            return None
        if hmac.compare_digest(str(pin).strip(), self.pin):
            self._fails.pop(who, None)
            return True
        self._fails[who] = fails + [now]
        return False

    # ------------------------------------------------------------------ idiomas
    def active_langs(self) -> list[str]:
        wanted = list(self.operator_langs) + [l.lang for l in self.listeners.values()]
        return clean_targets(wanted, self.src)

    def stats(self) -> dict:
        by_lang: dict[str, int] = {}
        for l in self.listeners.values():
            by_lang[l.lang] = by_lang.get(l.lang, 0) + 1
        return {"listeners": len(self.listeners), "langs": dict(sorted(by_lang.items())),
                "operator": self.operator is not None, "seq": self.seq, "pin": self.pin,
                "translate": self.translator.name if self.translator else None}

    async def _notify_operator(self) -> None:
        if self.operator:
            s = self.stats()
            await self._safe(self.operator, P.room(s["listeners"], s["langs"]))

    # ------------------------------------------------------------------ operador
    async def set_operator(self, send: Send | None, langs: list[str] | None = None) -> None:
        self.operator = send
        self.operator_langs = clean_targets(langs or [], self.src) if self.translator else []
        state = "live" if send else "waiting"
        for l in list(self.listeners.values()):
            await self._safe(l.send, P.room_state(state))
        await self._notify_operator()

    # ------------------------------------------------------------------ oyentes
    def _text_for(self, line: Line, lang: str) -> str | None:
        return line.text if lang == self.src else line.tr.get(lang)

    def _line_msg(self, line: Line, lang: str) -> dict:
        text = self._text_for(line, lang)
        return P.line(line.seq, text or "", lang, orig=line.text, pending=text is None)

    async def add_listener(self, listener: Listener, since: int | None = None,
                           epoch: str | None = None) -> None:
        old = self.listeners.get(listener.device)
        if old and old.close:                       # el mismo móvil otra vez: fuera el socket viejo
            try:
                await old.close()
            except Exception:  # noqa: BLE001
                pass
        listener.lang = self._lang_ok(listener.lang)
        self.listeners[listener.device] = listener
        await listener.send(P.welcome(self.epoch, listener.lang, self.src, self.make_token(),
                                      "live" if self.operator else "waiting"))
        if epoch == self.epoch and since is not None:
            replay = [ln for ln in self.lines if ln.seq > since]
        else:
            replay = list(self.lines)[-REPLAY_NEW:]
        await self._send_lines(listener, replay)
        await self._notify_operator()

    async def remove_listener(self, device: str, listener: Listener | None = None) -> None:
        current = self.listeners.get(device)
        if current is not None and (listener is None or current is listener):
            del self.listeners[device]
            await self._notify_operator()

    def _lang_ok(self, lang: str) -> str:
        lang = short_code(lang)
        return lang if lang in ALL_LANGUAGES else "es"

    async def change_lang(self, device: str, lang: str) -> None:
        l = self.listeners.get(device)
        if not l:
            return
        l.lang = self._lang_ok(lang)
        recent = list(self.lines)[-REPLAY_NEW:]
        await l.send(P.reset(l.lang))
        await self._send_lines(l, recent)
        # Las frases recientes que aún no existen en ese idioma se traducen ahora
        for ln in recent:
            if self._text_for(ln, l.lang) is None:
                self._enqueue(ln.seq)
        await self._notify_operator()

    async def _send_lines(self, l: Listener, lines: list[Line]) -> None:
        for ln in lines:
            await self._safe(l.send, self._line_msg(ln, l.lang))

    # ------------------------------------------------------------------ frases
    def _enqueue(self, seq: int) -> None:
        if self.translator:
            self.pending += 1
            self.queue.put_nowait(seq)

    async def publish_final(self, text: str, t_end: float | None = None) -> int:
        """Una frase definitiva: se numera, se reparte y se encarga su traducción."""
        self.seq += 1
        line = Line(self.seq, text, t_end or time.monotonic())
        self.lines.append(line)
        for l in list(self.listeners.values()):
            await self._safe(l.send, self._line_msg(line, l.lang))
        if self.translator and self.active_langs():
            self._enqueue(line.seq)
        return line.seq

    def _find(self, seq: int) -> Line | None:
        for ln in reversed(self.lines):
            if ln.seq == seq:
                return ln
        return None

    async def translate_one(self, seq: int) -> None:
        line = self._find(seq)
        targets = [t for t in self.active_langs() if line and t not in line.tr]
        if not line or not targets or not self.translator:
            return
        try:
            result, took = await self.translator.translate(line.text, self.src, targets)
        except Exception as exc:  # noqa: BLE001
            log.exception("Error al traducir")
            if self.operator:
                await self._safe(self.operator, P.translation(seq, {}, 0, error=str(exc)[:200]))
            return
        line.tr.update(result)
        if self.on_latency:
            self.on_latency(time.monotonic() - line.t, len(targets))
        if self.operator:
            mine = {k: v for k, v in result.items() if k in self.operator_langs}
            if mine:
                await self._safe(self.operator, P.translation(seq, mine, took))
        for l in list(self.listeners.values()):
            if l.lang in result:
                await self._safe(l.send, P.line(seq, result[l.lang], l.lang, orig=line.text))

    async def worker(self) -> None:
        """Traduce en orden; la transcripción nunca espera por esto."""
        while True:
            seq = await self.queue.get()
            try:
                await self.translate_one(seq)
            finally:
                self.pending -= 1

    def start(self) -> None:
        if self.translator and self._worker is None:
            self._worker = asyncio.create_task(self.worker())

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            self._worker = None

    async def wait_translations(self, seconds: float = 8.0) -> None:
        end = time.monotonic() + seconds
        while self.pending > 0 and time.monotonic() < end:
            await asyncio.sleep(0.05)

    @staticmethod
    async def _safe(send: Send, msg: dict) -> None:
        try:
            await send(msg)
        except Exception:  # noqa: BLE001  (un móvil que se fue no debe romper a los demás)
            pass
