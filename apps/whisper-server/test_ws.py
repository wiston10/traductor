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
        ["--engine", "mock", "--translate", "off", "--no-metrics", "--data-dir", tmp, *extra_args])
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
