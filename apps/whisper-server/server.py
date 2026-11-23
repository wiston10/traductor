#!/usr/bin/env python3
"""
Servidor local de reconocimiento de voz para suizo alemán.

Recibe audio PCM 16 kHz (int16, mono) desde la página web por WebSocket,
lo transcribe con un modelo Whisper ajustado para suizo alemán (que escribe
en alemán estándar) y devuelve texto provisional ("partial") y definitivo
("final"). La traducción la sigue haciendo el navegador.

Todo corre en este ordenador: gratis, sin claves y sin enviar audio a nadie.

Uso:
    python3 server.py                       # http://localhost:8765
    python3 server.py --model <modelo HF>   # otro modelo
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import logging
import time
from pathlib import Path

import numpy as np
from aiohttp import WSMsgType, web

import training_store as store
from idea import IdeaClient
from metrics import Metrics

SAMPLE_RATE = 16000
FRAME = 480  # 30 ms

log = logging.getLogger("whisper-server")


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "Flurin17/whisper-large-v3-turbo-swiss-german"
HERE = Path(__file__).resolve().parent
# Dónde deja tools/convert_to_mlx.sh el modelo suizo convertido a MLX
MLX_SWISS_PATH = HERE / "models" / "swiss-german-turbo-mlx"
MLX_ALIASES = {"turbo": "mlx-community/whisper-large-v3-turbo"}


class Transcriber:
    """Motor PyTorch (transformers). Funciona en cualquier sitio; en Mac es el más lento."""

    def __init__(self, model_id: str, device: str | None, language: str, vocab: str = ""):
        import torch
        from transformers import pipeline

        if device is None:
            if torch.backends.mps.is_available():
                device = "mps"
            elif torch.cuda.is_available():
                device = "cuda"
            else:
                device = "cpu"
        dtype = torch.float16 if device in ("mps", "cuda") else torch.float32
        log.info("Cargando %s en %s (%s)… la primera vez se descarga (~1,6 GB)", model_id, device, dtype)
        self.pipe = pipeline(
            "automatic-speech-recognition",
            model=model_id,
            torch_dtype=dtype,
            device=device,
        )
        self.language = language
        self.lock = asyncio.Lock()
        # Vocabulario opcional: Whisper lo usa como "contexto previo" y reconoce
        # mejor esos nombres. Máximo ~200 tokens (límite de Whisper).
        self.prompt_text = ""
        self.prompt_ids = None
        if vocab:
            try:
                ids = self.pipe.tokenizer.get_prompt_ids(vocab, return_tensors="pt")
                if len(ids) > 220:
                    log.warning("Vocabulario demasiado largo (%d tokens): se recorta a 220", len(ids))
                    ids = ids[:220]
                self.prompt_ids = ids.to(self.pipe.device)
                self.prompt_text = vocab.strip()
                self._run(np.zeros(SAMPLE_RATE, dtype=np.float32))   # comprobar que funciona
                log.info("Vocabulario activo (%d tokens)", len(ids))
            except Exception as exc:  # noqa: BLE001
                self.prompt_ids, self.prompt_text = None, ""
                log.warning("No se pudo activar el vocabulario (%s): se sigue sin él", exc)
        # Calentamiento: la primera inferencia siempre es lenta
        self._run(np.zeros(SAMPLE_RATE, dtype=np.float32))
        t0 = time.monotonic()
        self._run(np.zeros(5 * SAMPLE_RATE, dtype=np.float32))
        log.info("Modelo listo en %s. Un paso tarda ~%.2fs (ideal: menos de 1s).", device, time.monotonic() - t0)

    def _run(self, audio: np.ndarray) -> str:
        kwargs = {
            "language": self.language,
            "task": "transcribe",
            "num_beams": 1,          # búsqueda simple: mucho más rápida
            "do_sample": False,
            "max_new_tokens": 160,   # una frase de pocos segundos no necesita más
        }
        if self.prompt_ids is not None:
            kwargs["prompt_ids"] = self.prompt_ids
        out = self.pipe({"raw": audio, "sampling_rate": SAMPLE_RATE}, generate_kwargs=kwargs)
        return strip_prompt((out.get("text") or "").strip(), self.prompt_text)

    async def transcribe(self, audio: np.ndarray) -> str:
        async with self.lock:  # un solo modelo: una inferencia a la vez
            return await asyncio.to_thread(self._run, audio)


def resolve_mlx_model(model: str) -> str:
    """Qué modelo MLX cargar. El suizo hay que convertirlo antes (tools/convert_to_mlx.sh)."""
    if model in MLX_ALIASES:
        return MLX_ALIASES[model]
    if model == DEFAULT_MODEL:
        if (MLX_SWISS_PATH / "config.json").exists():
            return str(MLX_SWISS_PATH)
        raise SystemExit(
            "El modelo suizo todavía no está convertido a MLX.\n"
            "  Conviértelo (una vez):   bash tools/convert_to_mlx.sh\n"
            "  o prueba el turbo normal: python3 server.py --engine mlx --model turbo")
    return model


class MlxTranscriber:
    """
    Motor MLX (mlx-whisper): el sistema de Apple para sus chips. En las comparativas
    publicadas, varias veces más rápido que PyTorch en Mac con el mismo modelo.
    Todas las llamadas van por UN hilo propio: MLX no admite mezclar hilos.
    """

    def __init__(self, model: str, language: str, vocab: str = "", audio_ctx: str = "full"):
        from concurrent.futures import ThreadPoolExecutor
        try:
            import mlx_whisper  # noqa: F401
        except ImportError:
            raise SystemExit("Falta mlx-whisper. Instálalo:  .venv/bin/pip install -r requirements-mlx.txt")
        self.model = resolve_mlx_model(model)
        self.language = language
        self.prompt_text = " ".join(vocab.split()) if vocab else ""
        self.lock = asyncio.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")
        # «auto»: el codificador de Whisper procesa solo la duración real de la frase (+1 s)
        # en vez de 30 s rellenos de silencio. Mucho menos cálculo; EXPERIMENTAL (comparar textos).
        self.short = audio_ctx == "auto"
        self.fallbacks = 0            # frases que hubo que repetir con el contexto completo
        self._model = None
        log.info("Cargando %s con MLX%s… la primera vez se descarga", self.model,
                 " (contexto corto)" if self.short else "")
        self._call(np.zeros(SAMPLE_RATE, dtype=np.float32))            # carga + calentamiento
        t0 = time.monotonic()
        self._call(np.zeros(5 * SAMPLE_RATE, dtype=np.float32))
        log.info("Modelo listo (MLX). Un paso tarda ~%.2fs (ideal: menos de 1s).", time.monotonic() - t0)
        if self.prompt_text:
            log.info("Vocabulario activo")

    def _call(self, audio: np.ndarray) -> str:
        return self._pool.submit(self._transcribe_blocking, audio).result()

    # Mismo nombre que en el motor PyTorch (lo usa evaluate.py)
    _run = _call

    def _transcribe_blocking(self, audio: np.ndarray) -> str:
        if self.short:
            return self._short_blocking(audio)
        import mlx_whisper
        out = mlx_whisper.transcribe(
            audio.astype(np.float32),
            path_or_hf_repo=self.model,
            language=self.language,
            task="transcribe",
            temperature=0.0,                    # una sola pasada: sin reintentos (más rápido)
            condition_on_previous_text=False,   # cada frase es independiente
            initial_prompt=self.prompt_text or None,
            verbose=None,
        )
        return strip_prompt((out.get("text") or "").strip(), self.prompt_text)

    def _decode_ctx(self, audio: np.ndarray, ctx: int | None, max_tokens: int | None) -> tuple[str, object]:
        """Codifica el audio con un contexto de «ctx» posiciones (None = los 30 s completos) y decodifica."""
        import mlx.core as mx
        import mlx.nn as nn
        from mlx_whisper.audio import log_mel_spectrogram, pad_or_trim
        from mlx_whisper.decoding import DecodingOptions, decode
        from mlx_whisper.load_models import load_model

        if self._model is None:
            self._model = load_model(self.model, dtype=mx.float16)
        m = self._model
        full_ctx = m.dims.n_audio_ctx
        mel = log_mel_spectrogram(audio.astype(np.float32), n_mels=m.dims.n_mels)
        if ctx is None:
            ctx = full_ctx
        ctx = min(full_ctx, ctx)
        mel = pad_or_trim(mel, ctx * 2, axis=-2).astype(mx.float16)[None]

        enc = m.encoder                                           # codificador con posiciones recortadas
        x = nn.gelu(enc.conv1(mel))
        x = nn.gelu(enc.conv2(x))
        x = x + enc._positional_embedding[: x.shape[1]]
        for block in enc.blocks:
            x, _, _ = block(x)
        features = enc.ln_post(x)

        m.dims.n_audio_ctx = ctx      # así decode() reconoce las características ya calculadas
        try:
            res = decode(m, features, DecodingOptions(
                language=self.language, task="transcribe", temperature=0.0, sample_len=max_tokens,
                without_timestamps=True, fp16=True, prompt=self.prompt_text or None))
        finally:
            m.dims.n_audio_ctx = full_ctx
        r = res[0] if isinstance(res, list) else res
        return strip_prompt((r.text or "").strip(), self.prompt_text), r

    def _short_blocking(self, audio: np.ndarray) -> str:
        """
        Contexto corto (como «audio_ctx» de whisper.cpp): procesa la duración real + 1 s en vez de 30 s.
        Su fallo típico son los bucles («haben wir Sachen, haben wir Sachen…»), así que:
          - se limita la respuesta a lo que cabe en la duración de la frase, y
          - si sale repetitiva o demasiado larga, se repite con el contexto completo (más lento, fiable).
        """
        secs = len(audio) / SAMPLE_RATE
        frames = int(secs * SAMPLE_RATE / 160) + 1
        max_tokens = int(secs * 7) + 12                 # ~4 tokens/s al hablar rápido, con margen
        text, r = self._decode_ctx(audio, (frames + 1) // 2 + 50, max_tokens)
        if r.no_speech_prob > 0.6 and r.avg_logprob < -1.0:      # silencio/ruido
            return ""
        if looks_broken(text, len(r.tokens), max_tokens):
            self.fallbacks += 1
            text, r = self._decode_ctx(audio, None, None)
            if r.no_speech_prob > 0.6 and r.avg_logprob < -1.0:
                return ""
        return text

    async def transcribe(self, audio: np.ndarray) -> str:
        async with self.lock:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._pool, self._transcribe_blocking, audio)


def make_transcriber(engine: str, model: str, device: str | None, language: str, vocab: str = "",
                     audio_ctx: str = "full"):
    if engine == "mlx":
        return MlxTranscriber(model, language, vocab, audio_ctx)
    return Transcriber(model, device, language, vocab)


# ---------------------------------------------------------------------------
# Segmentación del audio en directo
# ---------------------------------------------------------------------------
# Frases típicas que Whisper "alucina" sobre silencio o música
HALLUCINATIONS = {
    "untertitel im auftrag des zdf",
    "untertitel der amara.org-community",
    "vielen dank fürs zuschauen",
    "danke fürs zuschauen",
    "copyright wdr",
    "swr 2020",
}


def looks_broken(text: str, n_tokens: int = 0, max_tokens: int = 0) -> bool:
    """¿La transcripción está en bucle o es anormalmente larga? (fallo típico del contexto corto)"""
    import zlib
    t = text.strip()
    if not t:
        return False
    if max_tokens and n_tokens >= max_tokens:               # agotó el límite: casi seguro un bucle
        return True
    words = re.findall(r"\w+", t.lower())
    if len(words) >= 6:
        trigrams = [tuple(words[i:i + 3]) for i in range(len(words) - 2)]
        if max(trigrams.count(g) for g in set(trigrams)) >= 3:   # la misma secuencia 3 veces o más
            return True
        bigrams = [tuple(words[i:i + 2]) for i in range(len(words) - 1)]
        if max(bigrams.count(g) for g in set(bigrams)) >= 3:     # «ein Säge ein Säge ein Säge»
            return True
    data = t.encode("utf-8")
    return len(data) > 60 and len(data) / len(zlib.compress(data)) > 2.2   # texto muy repetitivo


def strip_prompt(text: str, prompt: str) -> str:
    """Algunas versiones de transformers devuelven el vocabulario delante del texto: se quita."""
    if prompt and text.startswith(prompt):
        return text[len(prompt):].strip()
    return text


def echoes_prompt(text: str, prompt: str) -> bool:
    """Con silencio, Whisper a veces "lee" el vocabulario en vez de escuchar: se descarta."""
    if not prompt:
        return False
    words = [w.strip(".,;:!?").lower() for w in text.split()]
    vocab = {w.strip(".,;:!?").lower() for w in prompt.split()}
    return len(words) >= 3 and sum(w in vocab for w in words) / len(words) > 0.8


def is_hallucination(text: str) -> bool:
    t = text.lower().strip(" .!?…")
    return not t or any(h in t for h in HALLUCINATIONS)


class Segmenter:
    """
    Acumula audio y decide cuándo transcribir:
      - cada `partial_every` s: texto provisional del segmento actual
      - tras `silence` s de pausa: cierra la frase (texto definitivo)
      - si nadie hace pausa (predicador rápido): corta como máximo a `max_seg` s,
        en el punto más silencioso de los últimos segundos, para no partir palabras.
    """

    def __init__(self, partial_every: float, silence: float, max_seg: float):
        self.partial_every = partial_every
        self.silence = silence
        self.max_seg = max_seg
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
            if speech.sum() * FRAME / SAMPLE_RATE < 0.25:
                return None, None
            return "final", audio

        if self.seconds >= self.max_seg:
            # Cortar en el marco más silencioso de los últimos 2 s
            window = int(2.0 * SAMPLE_RATE / FRAME)
            start = max(0, len(rms) - window)
            cut_frame = start + int(np.argmin(rms[start:]))
            return "final", self._cut(max(cut_frame, 1) * FRAME)

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
        return audio if has_speech else None

    def _cut(self, n: int) -> np.ndarray:
        audio, self.buf = self.buf[:n], self.buf[n:]
        self.last_partial = 0.0
        self.last_partial_len = 0
        self.last_partial_text = ""
        return audio


# ---------------------------------------------------------------------------
# Servidor web + WebSocket
# ---------------------------------------------------------------------------
def origin_allowed(origin: str | None, extra: list[str]) -> bool:
    if not origin or origin == "null":          # archivo abierto con doble clic
        return True
    if origin in extra:
        return True
    try:
        from urllib.parse import urlparse
        return urlparse(origin).hostname in {"localhost", "127.0.0.1", "::1"}
    except ValueError:
        return False


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    app = request.app
    if not origin_allowed(request.headers.get("Origin"), app["args"].allow_origin):
        log.warning("Conexión rechazada desde %s", request.headers.get("Origin"))
        raise web.HTTPForbidden(text="Origen no permitido")
    transcriber: Transcriber = app["transcriber"]
    args = app["args"]
    ws = web.WebSocketResponse(max_msg_size=4 * 1024 * 1024)
    await ws.prepare(request)
    log.info("Cliente conectado")

    seg = Segmenter(args.partial_every, args.silence, args.max_seg)
    closed = asyncio.Event()
    recorder: store.Recorder | None = None     # solo si la página activa «Guardar para entrenamiento»

    async def keep(audio: np.ndarray, text: str) -> None:
        """Guarda la frase (audio + texto) si está activado el modo entrenamiento."""
        if recorder is None:
            return
        try:
            await asyncio.to_thread(recorder.save, audio, text)
            if not ws.closed:
                await ws.send_str(json.dumps({"type": "saved", "count": recorder.count,
                                              "minutes": round(recorder.seconds / 60, 1),
                                              "session": recorder.dir.name if recorder.dir else ""}))
        except Exception:  # noqa: BLE001
            log.exception("No se pudo guardar la frase para entrenamiento")

    async def send(kind: str, text: str, level: str | None = None) -> None:
        if not ws.closed:
            msg = {"type": kind, "text": text}
            if level:
                msg["level"] = level
            await ws.send_str(json.dumps(msg, ensure_ascii=False))

    async def worker() -> None:
        await send("status", "Escuchando (Whisper local)")
        while not closed.is_set():
            await asyncio.sleep(0.15)
            kind, audio = seg.decide(time.monotonic())
            if kind is None:
                continue
            # Si el modelo está ocupado, un parcial se salta; un final espera.
            if kind == "partial" and transcriber.lock.locked():
                continue
            t0 = time.monotonic()
            try:
                text = await transcriber.transcribe(audio)
            except Exception as exc:  # noqa: BLE001
                log.exception("Error al transcribir")
                await send("status", f"Error: {exc}")
                continue
            took = time.monotonic() - t0
            seg.note_cost(took)
            app["metrics"].whisper_step(kind, len(audio) / SAMPLE_RATE, took)
            log.debug("%s %.1fs audio en %.2fs: %s", kind, len(audio) / SAMPLE_RATE, took, text)
            if is_hallucination(text) or echoes_prompt(text, transcriber.prompt_text):
                if kind == "final":
                    await send("partial", "")
                continue
            if kind == "final":
                await send("final", text)
                await keep(audio, text)
            elif text != seg.last_partial_text:
                seg.last_partial_text = text
                await send("partial", text)
            # Aviso solo si el Mac va lento de forma sostenida
            if seg.step_cost > 2.5:
                await send("status", f"Whisper va lento ({seg.step_cost:.1f}s por paso)", "warn")
            elif kind == "final":
                await send("status", f"Escuchando · {seg.step_cost:.1f}s por paso", "live")

    async def flush() -> None:
        audio = seg.flush()
        if audio is not None:
            try:
                text = await transcriber.transcribe(audio)
                if not is_hallucination(text) and not echoes_prompt(text, transcriber.prompt_text):
                    await send("final", text)
                    await keep(audio, text)
            except Exception:  # noqa: BLE001
                log.exception("Error al transcribir lo pendiente")
        await send("flushed", "")

    task = asyncio.create_task(worker())
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                seg.add(msg.data)
            elif msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if data.get("type") == "config":
                    if data.get("save") and recorder is None:
                        recorder = store.Recorder(app["data_dir"])
                        log.info("Guardando frases para entrenamiento en %s", app["data_dir"])
                    elif not data.get("save"):
                        recorder = None
                elif data.get("type") == "flush":
                    closed.set()          # el trabajador deja de cortar mientras vaciamos
                    await flush()
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        closed.set()
        task.cancel()
        log.info("Cliente desconectado")
    return ws


def _check_origin(request: web.Request) -> None:
    if not origin_allowed(request.headers.get("Origin"), request.app["args"].allow_origin):
        raise web.HTTPForbidden(text="Origen no permitido")


def _api_errors(fn):
    async def wrapper(request: web.Request):
        try:
            return await fn(request)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
        except FileNotFoundError:
            raise web.HTTPNotFound(text="No existe")
    return wrapper


@_api_errors
async def api_sessions(request: web.Request) -> web.Response:
    _check_origin(request)
    return web.json_response(await asyncio.to_thread(store.list_sessions, request.app["data_dir"]))


@_api_errors
async def api_session(request: web.Request) -> web.Response:
    _check_origin(request)
    return web.json_response(await asyncio.to_thread(
        store.get_session, request.app["data_dir"], request.match_info["sid"]))


@_api_errors
async def api_update_segment(request: web.Request) -> web.Response:
    _check_origin(request)
    body = await request.json()
    rec = await asyncio.to_thread(store.update_segment, request.app["data_dir"], request.match_info["sid"],
                                  request.match_info["seg"], body.get("text"), body.get("status", ""))
    return web.json_response(rec)


@_api_errors
async def api_session_meta(request: web.Request) -> web.Response:
    _check_origin(request)
    body = await request.json()
    meta = await asyncio.to_thread(store.set_session_meta, request.app["data_dir"], request.match_info["sid"],
                                   body.get("purpose"), body.get("note"))
    return web.json_response(meta)


@_api_errors
async def api_audio(request: web.Request) -> web.StreamResponse:
    sid, seg = request.match_info["sid"], request.match_info["seg"]
    if not store.SESSION_RE.match(sid) or not store.SEGMENT_RE.match(seg):
        raise ValueError("ruta no válida")
    path = request.app["data_dir"] / sid / f"{seg}.wav"
    if not path.exists():
        raise FileNotFoundError(seg)
    return web.FileResponse(path, headers={"Cache-Control": "no-store"})


def _cors(request: web.Request, resp: web.StreamResponse) -> web.StreamResponse:
    """Permite usar el modo idea desde la página abierta en otro puerto local."""
    origin = request.headers.get("Origin")
    if origin and origin_allowed(origin, request.app["args"].allow_origin):
        resp.headers["Access-Control-Allow-Origin"] = origin
    return resp


async def api_idea_status(request: web.Request) -> web.Response:
    _check_origin(request)
    return _cors(request, web.json_response(await request.app["idea"].status()))


async def api_idea(request: web.Request) -> web.Response:
    _check_origin(request)
    try:
        # La página lo envía como text/plain para evitar la consulta previa CORS
        body = json.loads(await request.text())
        latest = str(body.get("text", ""))[:2000]
        context = [str(c)[:1000] for c in body.get("context", [])][-4:]
        src, tgt = str(body.get("src", "de"))[:5], str(body.get("tgt", "es"))[:5]
        literal = str(body.get("literal", ""))[:2000]
        context_literal = [str(c)[:1000] for c in body.get("context_literal", [])][-4:]
    except (ValueError, AttributeError, TypeError):
        raise web.HTTPBadRequest(text="Petición no válida")
    if not latest.strip():
        return _cors(request, web.json_response({"idea": "", "ms": 0}))
    metrics: Metrics = request.app["metrics"]
    # Protección: la transcripción es lo esencial. Si Whisper va lento, las ideas esperan.
    if metrics.whisper_overloaded(request.app["args"].idea_pause):
        metrics.log("idea", ms=0, result="paused", whisper_cost=round(metrics.whisper_cost, 2))
        return _cors(request, web.json_response({"paused": True, "whisper_cost": round(metrics.whisper_cost, 1)}))
    try:
        result = await request.app["idea"].idea(context, latest, src, tgt, literal, context_literal)
    except Exception as exc:  # noqa: BLE001
        log.warning("Modo idea: %s", exc)
        metrics.log("idea", ms=0, result="error", error=str(exc)[:120])
        return _cors(request, web.json_response({"error": str(exc)[:200]}, status=503))
    outcome = ("busy" if result.get("busy") else "error" if result.get("error")
               else "ok" if result.get("idea") else "empty")
    metrics.log("idea", ms=result.get("ms", 0), result=outcome)
    return _cors(request, web.json_response(result))


async def corregir(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(request.app["web_dir"] / "corregir.html")


async def index(request: web.Request) -> web.StreamResponse:
    page = request.app["web_dir"] / "index.html"
    if page.exists():
        return web.FileResponse(page)
    return web.Response(text="Servidor Whisper activo. Abre la página web del apuntador.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Servidor Whisper local para suizo alemán")
    parser.add_argument("--engine", choices=("torch", "mlx"), default="torch",
                        help="Motor: torch (actual) o mlx (Apple, mucho más rápido en Mac; ver README)")
    parser.add_argument("--audio-ctx", choices=("full", "auto"), default="full",
                        help="Solo MLX. auto = procesar solo la duración real de cada frase (mucho más rápido, "
                             "experimental: comprobar con bench_asr.py que acierta igual)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="Modelo (por defecto: Whisper turbo ajustado a suizo alemán). "
                             "Con --engine mlx también: «turbo» (Whisper turbo normal, sin conversión)")
    parser.add_argument("--language", default="de", help="Idioma de salida de Whisper (de = alemán estándar)")
    parser.add_argument("--device", default=None, help="mps | cuda | cpu (por defecto, el mejor disponible)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--partial-every", type=float, default=1.0,
                        help="Segundos entre textos provisionales (más bajo = más rápido, más carga; "
                             "0 = desactivar: solo frases definitivas, la mitad de trabajo)")
    parser.add_argument("--silence", type=float, default=0.5,
                        help="Pausa (s) que cierra una frase")
    parser.add_argument("--max-seg", type=float, default=6.0,
                        help="Duración máxima (s) de un segmento si el predicador no hace pausas")
    parser.add_argument("--vocab", nargs="?", const=str(Path(__file__).resolve().parent / "vocab" / "de.txt"),
                        default="", metavar="ARCHIVO",
                        help="Activar vocabulario bíblico para Whisper (por defecto vocab/de.txt)")
    parser.add_argument("--data-dir", default=str(Path(__file__).resolve().parent / "training-data"),
                        help="Carpeta donde se guardan las frases para entrenamiento")
    parser.add_argument("--idea-model", default="gemma3:4b",
                        help="Modelo de Ollama SIN razonamiento para el modo idea (por defecto gemma3:4b)")
    parser.add_argument("--idea-input", choices=("ambos", "literal"), default="literal",
                        help="Qué recibe el modelo: solo la traducción literal (por defecto: más fiel en las "
                             "pruebas con gemma3:4b) u original + traducción literal")
    parser.add_argument("--idea-pause", type=float, default=2.0, metavar="SEG",
                        help="Pausar el modo idea mientras Whisper tarde más de SEG por paso (protege la transcripción)")
    parser.add_argument("--no-metrics", action="store_true",
                        help="No guardar el registro de rendimiento en metrics/")
    parser.add_argument("--allow-origin", action="append", default=[],
                        help="Permitir otra web (p. ej. https://usuario.github.io). Repetible.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    # Silenciar mensajes técnicos que no son errores (descargas, avisos de transformers)
    for noisy in ("httpx", "huggingface_hub", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        from transformers.utils import logging as hf_logging
        hf_logging.set_verbosity_error()
    except Exception:  # noqa: BLE001
        pass

    app = web.Application()
    app["args"] = args
    app["web_dir"] = (Path(__file__).resolve().parent.parent / "web")
    vocab = ""
    if args.vocab:
        vp = Path(args.vocab)
        if vp.exists():
            vocab = " ".join(vp.read_text(encoding="utf-8").split())
        else:
            log.warning("No existe el vocabulario %s: se sigue sin él", vp)
    app["transcriber"] = make_transcriber(args.engine, args.model, args.device, args.language, vocab,
                                          args.audio_ctx)
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app["data_dir"] = Path(args.data_dir)
    app.router.add_get("/corregir", corregir)
    app["idea"] = IdeaClient(args.idea_model, input_mode=args.idea_input)
    app["metrics"] = Metrics(Path(__file__).resolve().parent / "metrics", enabled=not args.no_metrics)
    app["metrics"].log("start", model=args.model, engine=args.engine, audio_ctx=args.audio_ctx, idea_model=args.idea_model, idea_input=args.idea_input,
                       max_seg=args.max_seg, partial_every=args.partial_every, vocab=bool(args.vocab))
    app.router.add_get("/api/idea/status", api_idea_status)
    app.router.add_post("/api/idea", api_idea)

    async def _close_idea(app_: web.Application) -> None:
        await app_["idea"].close()
    app.on_cleanup.append(_close_idea)
    app.router.add_get("/api/sessions", api_sessions)
    app.router.add_get("/api/sessions/{sid}", api_session)
    app.router.add_post("/api/sessions/{sid}", api_session_meta)
    app.router.add_post("/api/sessions/{sid}/segments/{seg}", api_update_segment)
    app.router.add_get("/api/audio/{sid}/{seg}", api_audio)
    app.router.add_static("/static", app["web_dir"], show_index=False)
    if (app["web_dir"] / "glossary").is_dir():
        app.router.add_static("/glossary", app["web_dir"] / "glossary", show_index=False)

    log.info("Abre http://%s:%d en Chrome", "localhost" if args.host == "127.0.0.1" else args.host, args.port)
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
