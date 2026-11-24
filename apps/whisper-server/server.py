#!/usr/bin/env python3
"""
Servidor local: reconocimiento de voz (Whisper) + traducción (NLLB) en este ordenador.

Recibe audio PCM 16 kHz (int16, mono) desde la página web por WebSocket, lo transcribe
con Whisper (por defecto el modelo ajustado a suizo alemán, que escribe en alemán estándar)
y, si está activada, traduce cada frase a los idiomas que pide la página.

Todo corre en este ordenador: gratis, sin claves y sin enviar audio a nadie.

Módulos:
  segmenter.py  corte del audio en frases (+ puerta de volumen)
  asr.py        motores Whisper (torch, mlx, simulado) y filtros del texto
  translate.py  traducción NLLB, glosario y frases fijas
  dialect.py    palabras de dialecto → alemán estándar (lista revisada a mano)
  net.py        qué páginas pueden conectarse
  protocol.py   formato de los mensajes (versión y número de secuencia)

Uso:
    python3 server.py                       # http://localhost:8765
    python3 server.py --engine mock         # sin modelo (pruebas)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

import numpy as np
from aiohttp import WSMsgType, web

import protocol as P
import training_store as store
from asr import (DEFAULT_MODEL, MLX_SWISS_PATH, Transcriber, echoes_prompt, is_hallucination,  # noqa: F401
                 looks_broken, looks_like_list, make_transcriber, resolve_mlx_model, should_drop,
                 strip_prompt)
from dialect import Dialect
from idea import IdeaClient
from metrics import Metrics
from net import origin_allowed
from segmenter import FRAME, SAMPLE_RATE, Segmenter  # noqa: F401
from translate import TranslationService, clean_targets, load_backend, short_code

HERE = Path(__file__).resolve().parent
log = logging.getLogger("whisper-server")


# ---------------------------------------------------------------------------
# Una conexión de la página (el operador / intérprete que envía audio)
# ---------------------------------------------------------------------------
class Session:
    def __init__(self, app: web.Application, ws: web.WebSocketResponse):
        args = app["args"]
        self.app, self.ws, self.args = app, ws, args
        self.transcriber = app["transcriber"]
        self.translator: TranslationService | None = app["translator"]
        self.dialect: Dialect = app["dialect"]
        self.metrics: Metrics = app["metrics"]
        self.seg = Segmenter(args.partial_every, args.silence, args.max_seg, args.gate_db)
        self.closed = asyncio.Event()
        self.recorder: store.Recorder | None = None   # solo si la página activa «Guardar para entrenamiento»
        self.src = short_code(args.language)
        self.targets: list[str] = []
        self.seq = 0
        self.previous = ""                            # última frase (contexto para Whisper)
        self.tr_queue: asyncio.Queue[tuple[int, str]] = asyncio.Queue()
        self.tr_pending = 0                           # traducciones encargadas y aún sin enviar

    # --- envío ---
    async def send(self, msg: dict) -> None:
        if not self.ws.closed:
            await self.ws.send_str(json.dumps(msg, ensure_ascii=False))

    async def status(self, text: str, level: str | None = None) -> None:
        await self.send(P.status(text, level))

    # --- configuración que manda la página ---
    async def configure(self, data: dict) -> None:
        if data.get("save") and self.recorder is None:
            self.recorder = store.Recorder(self.app["data_dir"])
            log.info("Guardando frases para entrenamiento en %s", self.app["data_dir"])
        elif not data.get("save"):
            self.recorder = None
        if data.get("src"):
            # El idioma que transcribe el modelo manda; la página solo puede afinarlo (de-CH → de)
            page_src = short_code(str(data["src"]))
            if page_src != short_code(self.args.language):
                log.warning("La página dice idioma «%s» pero Whisper transcribe «%s»: se traduce desde «%s»",
                            page_src, self.args.language, short_code(self.args.language))
        self.targets = clean_targets(data.get("targets", []), self.src) if self.translator else []
        await self.send(P.config_ok(self.targets, self.translator.name if self.translator else None))

    # --- guardar para entrenamiento ---
    async def keep(self, audio: np.ndarray, text: str) -> None:
        if self.recorder is None:
            return
        try:
            await asyncio.to_thread(self.recorder.save, audio, text)
            await self.send(P.saved(self.recorder.count, self.recorder.seconds,
                                    self.recorder.dir.name if self.recorder.dir else ""))
        except Exception:  # noqa: BLE001
            log.exception("No se pudo guardar la frase para entrenamiento")

    # --- una frase definitiva ---
    async def publish_final(self, audio: np.ndarray, raw: str) -> None:
        text = self.dialect.apply(raw) if self.src == "de" else raw
        self.seq += 1
        self.previous = text
        await self.send(P.final(self.seq, text))
        await self.keep(audio, raw)       # se guarda lo que oyó Whisper, sin retoques
        if self.targets and self.translator:
            self.tr_pending += 1
            self.tr_queue.put_nowait((self.seq, text))

    async def translation_worker(self) -> None:
        """Traduce en orden, en su propio hilo: la transcripción nunca espera por esto."""
        while True:
            seq, text = await self.tr_queue.get()
            try:
                await self._translate_one(seq, text)
            finally:
                self.tr_pending -= 1

    async def _translate_one(self, seq: int, text: str) -> None:
        targets = list(self.targets)
        if not targets or self.ws.closed:
            return
        try:
            result, took = await self.translator.translate(text, self.src, targets)
        except Exception as exc:  # noqa: BLE001
            log.exception("Error al traducir")
            self.metrics.log("translate", ms=0, result="error", error=str(exc)[:120])
            await self.send(P.translation(seq, {}, 0, error=str(exc)[:200]))
            return
        self.metrics.log("translate", ms=round(took * 1000), langs=len(targets), chars=len(text),
                         queue=self.tr_queue.qsize())
        await self.send(P.translation(seq, result, took))

    # --- bucle de corte y transcripción ---
    async def worker(self) -> None:
        await self.status("Escuchando (Whisper local)")
        seg, tr = self.seg, self.transcriber
        while not self.closed.is_set():
            await asyncio.sleep(0.15)
            kind, audio = seg.decide(time.monotonic())
            if kind is None:
                continue
            # Si el modelo está ocupado, un parcial se salta; un final espera.
            if kind == "partial" and tr.lock.locked():
                continue
            t0 = time.monotonic()
            try:
                text = await tr.transcribe(audio, final=(kind == "final"), previous=self.previous)
            except Exception as exc:  # noqa: BLE001
                log.exception("Error al transcribir")
                await self.status(f"Error: {exc}")
                continue
            took = time.monotonic() - t0
            seg.note_cost(took)
            self.metrics.whisper_step(kind, len(audio) / SAMPLE_RATE, took)
            log.debug("%s %.1fs audio en %.2fs: %s", kind, len(audio) / SAMPLE_RATE, took, text)
            if should_drop(text, tr.prompt_text):
                if kind == "final":
                    await self.send(P.partial(""))
                continue
            if kind == "final":
                await self.publish_final(audio, text)
            elif text != seg.last_partial_text:
                seg.last_partial_text = text
                await self.send(P.partial(text))
            # Aviso solo si el Mac va lento de forma sostenida
            if seg.step_cost > 2.5:
                await self.status(f"Whisper va lento ({seg.step_cost:.1f}s por paso)", "warn")
            elif kind == "final":
                await self.status(f"Escuchando · {seg.step_cost:.1f}s por paso", "live")

    async def flush(self) -> None:
        audio = self.seg.flush()
        if audio is not None:
            try:
                text = await self.transcriber.transcribe(audio, final=True, previous=self.previous)
                if not should_drop(text, self.transcriber.prompt_text):
                    await self.publish_final(audio, text)
            except Exception:  # noqa: BLE001
                log.exception("Error al transcribir lo pendiente")
        # Esperar (poco) a que salgan las traducciones pendientes
        for _ in range(80):
            if self.tr_pending <= 0:
                break
            await asyncio.sleep(0.1)
        await self.send(P.flushed())


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    app = request.app
    if not origin_allowed(request.headers.get("Origin"), app["args"].allow_origin):
        log.warning("Conexión rechazada desde %s", request.headers.get("Origin"))
        raise web.HTTPForbidden(text="Origen no permitido")
    ws = web.WebSocketResponse(max_msg_size=4 * 1024 * 1024, heartbeat=20)
    await ws.prepare(request)
    log.info("Cliente conectado")
    s = Session(app, ws)
    tasks = [asyncio.create_task(s.worker())]
    if s.translator:
        tasks.append(asyncio.create_task(s.translation_worker()))
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                s.seg.add(msg.data)
            elif msg.type == WSMsgType.TEXT:
                data = P.parse(msg.data)
                if data is None:
                    continue
                if data.get("type") == "config":
                    await s.configure(data)
                elif data.get("type") == "flush":
                    s.closed.set()          # el trabajador deja de cortar mientras vaciamos
                    await s.flush()
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        s.closed.set()
        for t in tasks:
            t.cancel()
        log.info("Cliente desconectado")
    return ws


# ---------------------------------------------------------------------------
# API de la herramienta de corrección y del modo idea
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Servidor local: Whisper + traducción NLLB")
    parser.add_argument("--engine", choices=("torch", "mlx", "mock"), default="torch",
                        help="Motor: torch (por defecto), mlx (Apple, opcional) o mock (simulado, para pruebas)")
    parser.add_argument("--audio-ctx", choices=("full", "auto"), default="full",
                        help="Solo MLX. auto = procesar solo la duración real de cada frase (experimental)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="Modelo (por defecto: Whisper turbo ajustado a suizo alemán). "
                             "«turbo» = Whisper turbo general (para prédicas en otros idiomas)")
    parser.add_argument("--language", default="de",
                        help="Idioma de la prédica (de = alemán/suizo alemán; con otro idioma usa --model turbo)")
    parser.add_argument("--device", default=None, help="mps | cuda | cpu (por defecto, el mejor disponible)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--partial-every", type=float, default=0.0,
                        help="Segundos entre textos provisionales. Por defecto 0 = desactivado: solo frases "
                             "definitivas. Medido en un MacBook Air M3: con provisionales, 1 min de voz pedía "
                             "~78 s de cálculo y se quedaba atrás; sin ellos, ~30 s. Activar en Mac potentes: 1.0")
    parser.add_argument("--silence", type=float, default=0.5, help="Pausa (s) que cierra una frase")
    parser.add_argument("--max-seg", type=float, default=6.0,
                        help="Duración máxima (s) de un segmento si el predicador no hace pausas")
    parser.add_argument("--gate-db", type=float, default=-50.0,
                        help="Puerta de volumen (dBFS): frases más flojas no se mandan al modelo. "
                             "-50 solo quita casi-silencio; usa -200 para desactivarla")
    parser.add_argument("--beam", type=int, default=1,
                        help="Búsqueda amplia en frases definitivas (1 = la más rápida). Medir con evaluate.py")
    parser.add_argument("--context", choices=("none", "confirmed"), default="none",
                        help="confirmed = dar a Whisper el final de la frase anterior como contexto. "
                             "Medir con evaluate.py antes de usarlo")
    parser.add_argument("--vocab", nargs="?", const=str(HERE / "vocab" / "de.txt"),
                        default="", metavar="ARCHIVO",
                        help="Vocabulario bíblico para Whisper. APAGADO por defecto: una lista con comas puede "
                             "hacer que Whisper invente listas de palabras. Medir con evaluate.py --vocab")
    parser.add_argument("--translate", choices=("auto", "ct2", "transformers", "off", "fake"), default="auto",
                        help="Traducción NLLB en el servidor. auto = si está instalada (bash tools/setup_nllb.sh)")
    parser.add_argument("--mt-beams", type=int, default=1,
                        help="Búsqueda de la traducción. 1 = medido en un M3: 14 idiomas en 1,9 s por frase "
                             "(con 2: 3,1 s)")
    parser.add_argument("--mt-threads", type=int, default=4, help="Núcleos del procesador para traducir")
    parser.add_argument("--mt-device", choices=("cpu", "mps"), default="cpu",
                        help="Dónde traduce NLLB: cpu (deja la tarjeta gráfica a Whisper) o mps "
                             "(tarjeta gráfica, experimental; compite con Whisper). Elegir con bench_mt.py --comparar")
    parser.add_argument("--data-dir", default=str(HERE / "training-data"),
                        help="Carpeta donde se guardan las frases para entrenamiento")
    parser.add_argument("--idea-model", default="gemma3:4b",
                        help="Modelo de Ollama SIN razonamiento para el modo idea (por defecto gemma3:4b)")
    parser.add_argument("--idea-input", choices=("ambos", "literal"), default="literal",
                        help="Qué recibe el modelo: solo la traducción literal (por defecto) u original + literal")
    parser.add_argument("--idea-pause", type=float, default=2.0, metavar="SEG",
                        help="Pausar el modo idea mientras Whisper tarde más de SEG por paso")
    parser.add_argument("--no-metrics", action="store_true", help="No guardar el registro de rendimiento")
    parser.add_argument("--allow-origin", action="append", default=[],
                        help="Permitir otra web (p. ej. https://usuario.github.io). Repetible.")
    parser.add_argument("--verbose", action="store_true")
    return parser


def build_app(args: argparse.Namespace, transcriber=None, translator: TranslationService | None = None,
              metrics_dir: Path | None = None) -> web.Application:
    """Crea la aplicación. Las pruebas pasan su propio motor y traductor (sin modelos)."""
    app = web.Application()
    app["args"] = args
    app["web_dir"] = HERE.parent / "web"
    if transcriber is None:
        vocab = ""
        if args.vocab:
            vp = Path(args.vocab)
            if vp.exists():
                vocab = " ".join(vp.read_text(encoding="utf-8").split())
            else:
                log.warning("No existe el vocabulario %s: se sigue sin él", vp)
        transcriber = make_transcriber(args.engine, args.model, args.device, args.language, vocab,
                                       args.audio_ctx, args.beam, args.context)
    app["transcriber"] = transcriber
    if translator is None:
        backend = load_backend(args.translate, beams=args.mt_beams, threads=args.mt_threads,
                               device=args.mt_device)
        translator = TranslationService(backend) if backend else None
    app["translator"] = translator
    app["dialect"] = Dialect.load()
    if len(app["dialect"]):
        log.info("Dialecto: %d palabras revisadas → alemán estándar", len(app["dialect"]))
    app["data_dir"] = Path(args.data_dir)
    app["idea"] = IdeaClient(args.idea_model, input_mode=args.idea_input)
    app["metrics"] = Metrics(metrics_dir or HERE / "metrics", enabled=not args.no_metrics)
    app["metrics"].log("start", model=args.model, engine=args.engine, audio_ctx=args.audio_ctx,
                       idea_model=args.idea_model, idea_input=args.idea_input, max_seg=args.max_seg,
                       partial_every=args.partial_every, vocab=bool(args.vocab), beam=args.beam,
                       context=args.context, gate_db=args.gate_db,
                       translate=translator.name if translator else "off")

    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/corregir", corregir)
    app.router.add_get("/api/idea/status", api_idea_status)
    app.router.add_post("/api/idea", api_idea)
    app.router.add_get("/api/sessions", api_sessions)
    app.router.add_get("/api/sessions/{sid}", api_session)
    app.router.add_post("/api/sessions/{sid}", api_session_meta)
    app.router.add_post("/api/sessions/{sid}/segments/{seg}", api_update_segment)
    app.router.add_get("/api/audio/{sid}/{seg}", api_audio)
    if app["web_dir"].is_dir():
        app.router.add_static("/static", app["web_dir"], show_index=False)
    if (app["web_dir"] / "glossary").is_dir():
        app.router.add_static("/glossary", app["web_dir"] / "glossary", show_index=False)

    async def _close_idea(app_: web.Application) -> None:
        await app_["idea"].close()
    app.on_cleanup.append(_close_idea)
    return app


def main() -> None:
    args = build_parser().parse_args()
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
    app = build_app(args)
    if app["translator"]:
        log.info("Traducción en el servidor activa (%s)", app["translator"].name)
    log.info("Abre http://%s:%d en Chrome", "localhost" if args.host == "127.0.0.1" else args.host, args.port)
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
