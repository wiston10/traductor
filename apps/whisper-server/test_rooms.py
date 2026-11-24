#!/usr/bin/env python3
"""Pruebas de la sala (móviles de los oyentes) sin red: envíos y traductor simulados."""
import asyncio

import net
import rooms as R
import translate as T


class Phone:
    """Un móvil simulado: guarda lo que recibe."""

    def __init__(self, device, lang):
        self.got, self.closed = [], False
        self.listener = R.Listener(device=device, lang=lang, send=self.send, close=self.close)

    async def send(self, msg):
        self.got.append(msg)

    async def close(self):
        self.closed = True

    def lines(self):
        return [(m["seq"], m["text"], bool(m.get("pending"))) for m in self.got if m["type"] == "line"]

    def final_text(self, seq):
        done = [m["text"] for m in self.got if m["type"] == "line" and m["seq"] == seq and not m.get("pending")]
        return done[-1] if done else None


def run(coro):
    return asyncio.run(coro)


def test_pin_y_pase():
    room = R.Room("de", pin="4821")
    assert room.check_pin("4821", "1.2.3.4") is True
    assert room.check_pin("0000", "1.2.3.4") is False
    tok = room.make_token(now=1000)
    assert room.token_ok(tok, now=2000) and not room.token_ok(tok, now=1000 + R.TOKEN_HOURS * 3600 + 1)
    assert not room.token_ok(tok[:-1] + ("0" if tok[-1] != "0" else "1"), now=2000)     # firma alterada
    assert not room.token_ok("basura", now=2000)
    other = R.Room("de", pin="9999", secret=room.secret)
    assert not other.token_ok(tok, now=2000)              # si cambia el PIN, los pases viejos no valen
    assert len(R.Room("de").pin) == 4                      # PIN al azar de 4 cifras


def test_demasiados_intentos_de_pin():
    room = R.Room("de", pin="4821")
    for _ in range(R.PIN_TRIES):
        assert room.check_pin("1111", "5.6.7.8", now=100) is False
    assert room.check_pin("4821", "5.6.7.8", now=101) is None          # bloqueado aunque acierte
    assert room.check_pin("4821", "9.9.9.9", now=101) is True          # otra dirección: no
    assert room.check_pin("4821", "5.6.7.8", now=100 + 301) is True    # pasados 5 minutos, sí


def test_secreto_se_guarda():
    import tempfile
    from pathlib import Path
    p = Path(tempfile.mkdtemp()) / ".secret-sala"
    a = R.load_secret(p)
    assert len(a) == 32 and R.load_secret(p) == a          # el mismo en cada arranque


def test_reparto_por_idioma():
    async def go():
        fake = T.FakeBackend()
        room = R.Room("de", pin="1", translator=T.TranslationService(fake))
        room.start()
        op = Phone("operador", "es")
        await room.set_operator(op.send, ["es"])
        es, en, de = Phone("movil-es-01", "es"), Phone("movil-en-01", "en"), Phone("movil-de-01", "de")
        for p in (es, en, de):
            await room.add_listener(p.listener)
        assert room.active_langs() == ["es", "en"]           # el alemán es el original: no se traduce
        seq = await room.publish_final("Gott liebt uns.")
        await room.wait_translations()
        await room.stop()
        return room, fake, op, es, en, de, seq
    room, fake, op, es, en, de, seq = run(go())
    assert de.lines() == [(seq, "Gott liebt uns.", False)]               # original al momento
    assert es.lines()[0] == (seq, "", True) and es.final_text(seq) == "[es] Gott liebt uns."
    assert en.final_text(seq) == "[en] Gott liebt uns."
    assert len(fake.calls) == 1 and sorted(fake.calls[0][2]) == ["en", "es"]   # una sola traducción para todos
    tr = [m for m in op.got if m["type"] == "translation"]
    assert tr and tr[0]["tr"] == {"es": "[es] Gott liebt uns."}           # el operador, solo su idioma
    assert [m for m in op.got if m["type"] == "room"][-1]["listeners"] == 3
    assert all(m["state"] == "live" for p in (es, en, de) for m in p.got if m["type"] == "welcome")


def test_reconexion_recibe_lo_que_falta():
    async def go():
        room = R.Room("de", pin="1")
        await room.set_operator(Phone("op", "de").send)
        a = Phone("movil-aaaa-1", "de")
        await room.add_listener(a.listener)
        for i in range(3):
            await room.publish_final(f"Satz {i + 1}")
        await room.remove_listener("movil-aaaa-1", a.listener)
        for i in range(3, 5):
            await room.publish_final(f"Satz {i + 1}")             # mientras estaba sin conexión
        b = Phone("movil-aaaa-1", "de")
        await room.add_listener(b.listener, since=3, epoch=room.epoch)
        c = Phone("movil-cccc-1", "de")
        await room.add_listener(c.listener, since=3, epoch="otra-sala")   # sala nueva: contexto reciente
        return b, c
    b, c = run(go())
    assert [s for s, _t, _p in b.lines()] == [4, 5]
    assert [s for s, _t, _p in c.lines()] == [1, 2, 3, 4, 5][-R.REPLAY_NEW:]


def test_un_solo_socket_por_movil():
    async def go():
        room = R.Room("de", pin="1")
        first, second = Phone("mismo-movil-1", "es"), Phone("mismo-movil-1", "es")
        await room.add_listener(first.listener)
        await room.add_listener(second.listener)
        await room.remove_listener("mismo-movil-1", first.listener)    # el viejo se va: no borra al nuevo
        return room, first, second
    room, first, second = run(go())
    assert first.closed and not second.closed
    assert len(room.listeners) == 1 and room.listeners["mismo-movil-1"] is second.listener


def test_cambiar_de_idioma_traduce_lo_reciente():
    async def go():
        room = R.Room("de", pin="1", translator=T.TranslationService(T.FakeBackend()))
        room.start()
        p = Phone("movil-cambia-1", "de")
        await room.add_listener(p.listener)
        await room.publish_final("Erster Satz.")
        await room.publish_final("Zweiter Satz.")
        await room.change_lang("movil-cambia-1", "fr")
        await room.wait_translations()
        await room.stop()
        return p
    p = run(go())
    assert any(m["type"] == "reset" and m["lang"] == "fr" for m in p.got)
    assert p.final_text(1) == "[fr] Erster Satz." and p.final_text(2) == "[fr] Zweiter Satz."


def test_sin_traductor_y_movil_roto():
    async def go():
        room = R.Room("de", pin="1")                         # NLLB sin instalar
        ok = Phone("movil-bueno-1", "es")

        async def broken(_msg):
            raise ConnectionResetError("se fue")
        room.listeners["movil-roto-01"] = R.Listener("movil-roto-01", "en", broken)   # se cayó sin avisar
        await room.add_listener(ok.listener)
        seq = await room.publish_final("Gott liebt uns.")
        return room, ok, seq
    room, ok, seq = run(go())
    assert ok.lines() == [(seq, "", True)]                   # sin traducción: queda pendiente, no se rompe
    assert room.pending == 0 and sorted(room.active_langs()) == ["en", "es"]


def test_idioma_desconocido_y_estadisticas():
    async def go():
        room = R.Room("de", pin="1234")
        p = Phone("movil-raro-01", "xx")
        await room.add_listener(p.listener)
        return room, p
    room, p = run(go())
    assert p.listener.lang == "es"
    st = room.stats()
    assert st["listeners"] == 1 and st["langs"] == {"es": 1} and st["pin"] == "1234"


def test_acceso_solo_local():
    assert net.is_local("127.0.0.1") and net.is_local("::1")
    assert not net.is_local("192.168.1.20") and not net.is_local(None)
    assert net.is_public_path("/oyente") and net.is_public_path("/ws/oyente")
    assert not net.is_public_path("/ws") and not net.is_public_path("/api/sessions") and not net.is_public_path("/corregir")
    assert net.same_origin("http://192.168.1.5:8765", "192.168.1.5:8765")
    assert not net.same_origin("https://evil.example", "192.168.1.5:8765")
