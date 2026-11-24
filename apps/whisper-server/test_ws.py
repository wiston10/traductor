#!/usr/bin/env python3
"""
Prueba de punta a punta del servidor: página → audio → frase → traducción → página.
Usa el Whisper simulado y el traductor simulado: sin modelos, en cualquier ordenador.
Necesita aiohttp (si no está, se salta).
"""
import asyncio
import json
import tempfile

import numpy as np

SR = 16000


def _audio():
    t = np.arange(int(2 * SR)) / SR
    voice = 0.2 * np.sin(2 * np.pi * 200 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t))
    rng = np.random.default_rng(1)
    sil = rng.normal(0, 0.0008, SR)
    return (np.concatenate([sil, voice, sil]) * 32767).astype(np.int16)


async def _session(extra_args=(), targets=("es", "en")):
    from aiohttp.test_utils import TestClient, TestServer

    import asr
    import server
    import translate as T

    tmp = tempfile.mkdtemp()
    args = server.build_parser().parse_args(
        ["--engine", "mock", "--translate", "off", "--no-metrics", "--data-dir", tmp + "/td", *extra_args])
    mock = asr.MockTranscriber(context=args.context)
    app = server.build_app(args, transcriber=mock, translator=T.TranslationService(T.FakeBackend()))
    client = TestClient(TestServer(app))
    await client.start_server()
    msgs = []
    try:
        ws = await client.ws_connect("/ws")
        await ws.send_str(json.dumps({"type": "config", "save": False, "src": "de-CH", "targets": list(targets)}))
        pcm = _audio()
        for i in range(0, len(pcm), 1600):                 # como la página: trozos de 0,1 s
            await ws.send_bytes(pcm[i:i + 1600].tobytes())
        await asyncio.sleep(0.6)                           # el trabajador revisa cada 0,15 s
        await ws.send_str(json.dumps({"type": "flush"}))
        while True:
            m = json.loads((await ws.receive(timeout=5)).data)
            msgs.append(m)
            if m["type"] == "flushed":
                break
        await ws.close()
    finally:
        await client.close()
    return msgs, mock


def test_frase_y_traduccion_por_websocket():
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        return "SKIP"
    msgs, _ = asyncio.run(_session())
    ok = next(m for m in msgs if m["type"] == "config_ok")
    assert ok["translate"] == ["es", "en"] and ok["engine"] == "fake" and ok["v"] == 1
    finals = [m for m in msgs if m["type"] == "final"]
    trs = [m for m in msgs if m["type"] == "translation"]
    assert len(finals) == 1 and finals[0]["seq"] == 1 and "Sekunden" in finals[0]["text"], msgs
    assert len(trs) == 1 and trs[0]["seq"] == 1, msgs
    assert trs[0]["tr"] == {"es": "[es] " + finals[0]["text"], "en": "[en] " + finals[0]["text"]}
    assert msgs[-1]["type"] == "flushed"


def test_sin_idiomas_no_traduce():
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        return "SKIP"
    msgs, _ = asyncio.run(_session(targets=()))
    assert not [m for m in msgs if m["type"] == "translation"]
    assert [m for m in msgs if m["type"] == "final"]


async def _sala():
    from aiohttp import WSServerHandshakeError
    from aiohttp.test_utils import TestClient, TestServer

    import asr
    import server
    import translate as T

    tmp = tempfile.mkdtemp()
    args = server.build_parser().parse_args(
        ["--engine", "mock", "--translate", "off", "--no-metrics", "--data-dir", tmp + "/td", "--pin", "4821"])
    app = server.build_app(args, transcriber=asr.MockTranscriber(),
                           translator=T.TranslationService(T.FakeBackend()))
    client = TestClient(TestServer(app))
    await client.start_server()
    out = {}
    try:
        # Una web ajena no puede conectarse a la sala
        try:
            await client.ws_connect("/ws/oyente", headers={"Origin": "https://evil.example"})
            out["evil"] = "conectó"
        except WSServerHandshakeError as exc:
            out["evil"] = exc.status
        # PIN incorrecto
        bad = await client.ws_connect("/ws/oyente")
        await bad.send_str(json.dumps({"type": "hello", "pin": "0000", "device": "movil-malo-01", "lang": "en"}))
        out["bad"] = json.loads((await bad.receive(timeout=5)).data)
        await bad.close()
        # PIN correcto, en inglés
        phone = await client.ws_connect("/ws/oyente")
        await phone.send_str(json.dumps({"type": "hello", "pin": "4821", "device": "movil-bueno-01", "lang": "en"}))
        welcome = json.loads((await phone.receive(timeout=5)).data)
        out["welcome"] = welcome
        # El operador transcribe una frase (y pide español para él)
        op = await client.ws_connect("/ws")
        await op.send_str(json.dumps({"type": "config", "save": False, "src": "de", "targets": ["es"]}))
        pcm = _audio()
        for i in range(0, len(pcm), 1600):
            await op.send_bytes(pcm[i:i + 1600].tobytes())
        await asyncio.sleep(0.6)
        await op.send_str(json.dumps({"type": "flush"}))
        op_msgs = []
        while True:
            m = json.loads((await op.receive(timeout=5)).data)
            op_msgs.append(m)
            if m["type"] == "flushed":
                break
        out["op"] = op_msgs
        phone_msgs = []
        while True:
            m = json.loads((await phone.receive(timeout=5)).data)
            phone_msgs.append(m)
            if m["type"] == "line" and not m.get("pending"):
                break
        out["phone"] = phone_msgs
        await phone.close()
        # Vuelve con su pase (sin PIN) y recibe lo que ya se dijo
        again = await client.ws_connect("/ws/oyente")
        await again.send_str(json.dumps({"type": "hello", "token": welcome["token"], "device": "movil-bueno-01",
                                         "lang": "en", "epoch": welcome["epoch"], "since": 0}))
        out["again"] = [json.loads((await again.receive(timeout=5)).data) for _ in range(2)]
        await again.close()
        await op.close()
        r = await client.get("/api/room")
        out["room"] = await r.json()
    finally:
        await client.close()
    return out


def test_sala_con_moviles():
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        return "SKIP"
    out = asyncio.run(_sala())
    assert out["evil"] == 403, out["evil"]
    assert out["bad"]["type"] == "error" and out["bad"]["code"] == "pin"
    assert out["welcome"]["type"] == "welcome" and out["welcome"]["lang"] == "en" and out["welcome"]["token"]
    final = next(m for m in out["op"] if m["type"] == "final")
    assert any(m["type"] == "translation" and m["tr"] == {"es": "[es] " + final["text"]} for m in out["op"])
    lines = [m for m in out["phone"] if m["type"] == "line"]
    assert lines[0]["pending"] and lines[-1]["text"] == "[en] " + final["text"]
    assert out["again"][0]["type"] == "welcome" and out["again"][1]["text"] == "[en] " + final["text"]
    assert out["room"]["pin"] == "4821" and out["room"]["reachable"] is False   # arrancado solo en local
