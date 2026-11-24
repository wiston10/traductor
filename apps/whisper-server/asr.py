"""
Motores de transcripción (Whisper) y filtros del texto que devuelven.

  - Transcriber      PyTorch (transformers). El de por defecto.
  - MlxTranscriber   MLX (Apple). Opcional.
  - MockTranscriber  Simulado: no carga ningún modelo. Para pruebas y CI.

Opciones medibles (comparar con evaluate.py antes de usarlas en un culto):
  - beams:   búsqueda más amplia en las frases definitivas (más lento, quizá más acierto).
  - context: «confirmed» = se da a Whisper el final de la frase anterior como contexto.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import zlib
from pathlib import Path

import numpy as np

from segmenter import SAMPLE_RATE

log = logging.getLogger("whisper-server")

DEFAULT_MODEL = "Flurin17/whisper-large-v3-turbo-swiss-german"
GENERAL_MODEL = "openai/whisper-large-v3-turbo"      # para prédicas en otros idiomas
HERE = Path(__file__).resolve().parent
# Dónde deja tools/convert_to_mlx.sh el modelo suizo convertido a MLX
MLX_SWISS_PATH = HERE / "models" / "swiss-german-turbo-mlx"
MLX_ALIASES = {"turbo": "mlx-community/whisper-large-v3-turbo"}
TORCH_ALIASES = {"turbo": GENERAL_MODEL}

CONTEXT_CHARS = 200      # cuánto texto anterior se da como contexto
CONTEXT_TOKENS = 50      # y como mucho estos tokens, para que no pese más que el audio


def context_tail(previous: str) -> str:
    """Final de la frase anterior, cortado por una palabra entera."""
    t = " ".join(previous.split())
    if len(t) <= CONTEXT_CHARS:
        return t
    cut = t[-CONTEXT_CHARS:]
    return cut[cut.find(" ") + 1:] if " " in cut else cut


# ---------------------------------------------------------------------------
# Filtros del texto
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


def looks_like_list(text: str) -> bool:
    """
    Lista de palabras sueltas separadas por comas, sin frase: lo que Whisper «lee» de un
    vocabulario cuando no oye nada claro (Barnaba documentó el mismo fallo con su glosario).
    """
    parts = [p.strip() for p in text.strip(" .").split(",") if p.strip()]
    if len(parts) < 4:
        return False
    short = sum(len(p.split()) <= 2 for p in parts)
    return short / len(parts) >= 0.8


def strip_prompt(text: str, prompt: str) -> str:
    """Algunas versiones de transformers devuelven el contexto delante del texto: se quita."""
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


def should_drop(text: str, prompt: str = "") -> bool:
    """¿Se descarta este texto en vez de mostrarlo?"""
    return is_hallucination(text) or echoes_prompt(text, prompt) or looks_like_list(text)


# ---------------------------------------------------------------------------
# Motores
# ---------------------------------------------------------------------------
class _Base:
    """Lo común: una inferencia a la vez y las opciones medibles."""
    prompt_text = ""        # vocabulario fijo (si se activó --vocab)

    def __init__(self, beams: int = 1, context: str = "none"):
        self.beams = max(1, int(beams))
        self.context = context
        self.lock = asyncio.Lock()

    def _run(self, audio: np.ndarray, final: bool = True, previous: str = "") -> str:
        raise NotImplementedError

    def prompt_for(self, previous: str) -> str:
        """Qué contexto recibe Whisper: el vocabulario manda; si no, el final de la frase anterior."""
        if self.prompt_text:
            return self.prompt_text
        if self.context == "confirmed" and previous:
            return context_tail(previous)
        return ""

    async def transcribe(self, audio: np.ndarray, final: bool = True, previous: str = "") -> str:
        async with self.lock:  # un solo modelo: una inferencia a la vez
            return await asyncio.to_thread(self._run, audio, final, previous)


class Transcriber(_Base):
    """Motor PyTorch (transformers). Funciona en cualquier sitio; en Mac es el más lento."""

    def __init__(self, model_id: str, device: str | None, language: str, vocab: str = "",
                 beams: int = 1, context: str = "none"):
        super().__init__(beams, context)
        import torch
        from transformers import pipeline

        model_id = TORCH_ALIASES.get(model_id, model_id)
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
        # Vocabulario opcional: Whisper lo usa como "contexto previo" y reconoce
        # mejor esos nombres. Máximo ~200 tokens (límite de Whisper).
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
        if self.beams > 1:
            log.info("Búsqueda amplia en frases definitivas: beam %d", self.beams)
        if self.context == "confirmed":
            log.info("Contexto: final de la frase anterior (máx. %d caracteres)", CONTEXT_CHARS)

    def _prompt_ids(self, prompt: str):
        if not prompt:
            return None
        if prompt == self.prompt_text:
            return self.prompt_ids
        import torch
        ids = self.pipe.tokenizer.get_prompt_ids(prompt, return_tensors="pt")
        # El primer token es de control (<|startofprev|>): se conserva y se recorta el texto por delante
        if len(ids) > CONTEXT_TOKENS + 1:
            ids = torch.cat([ids[:1], ids[-CONTEXT_TOKENS:]])
        return ids.to(self.pipe.device)

    def _run(self, audio: np.ndarray, final: bool = True, previous: str = "") -> str:
        kwargs = {
            "language": self.language,
            "task": "transcribe",
            "num_beams": self.beams if final else 1,    # los provisionales, siempre lo más rápido
            "do_sample": False,
            "max_new_tokens": 160,   # una frase de pocos segundos no necesita más
        }
        prompt = self.prompt_for(previous)
        ids = self._prompt_ids(prompt)
        if ids is not None:
            kwargs["prompt_ids"] = ids
        out = self.pipe({"raw": audio, "sampling_rate": SAMPLE_RATE}, generate_kwargs=kwargs)
        return strip_prompt((out.get("text") or "").strip(), prompt)


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


class MlxTranscriber(_Base):
    """
    Motor MLX (mlx-whisper): el sistema de Apple para sus chips.
    Todas las llamadas van por UN hilo propio: MLX no admite mezclar hilos.
    """

    def __init__(self, model: str, language: str, vocab: str = "", audio_ctx: str = "full",
                 beams: int = 1, context: str = "none"):
        super().__init__(1, context)
        from concurrent.futures import ThreadPoolExecutor
        try:
            import mlx_whisper  # noqa: F401
        except ImportError:
            raise SystemExit("Falta mlx-whisper. Instálalo:  .venv/bin/pip install -r requirements-mlx.txt")
        if beams > 1:
            log.warning("MLX no tiene búsqueda amplia (beam): se usa beam 1")
        self.model = resolve_mlx_model(model)
        self.language = language
        self.prompt_text = " ".join(vocab.split()) if vocab else ""
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")
        # «auto»: el codificador de Whisper procesa solo la duración real de la frase (+1 s)
        # en vez de 30 s rellenos de silencio. Mucho menos cálculo; EXPERIMENTAL (comparar textos).
        self.short = audio_ctx == "auto"
        self.fallbacks = 0            # frases que hubo que repetir con el contexto completo
        self._model = None
        log.info("Cargando %s con MLX%s… la primera vez se descarga", self.model,
                 " (contexto corto)" if self.short else "")
        self._run(np.zeros(SAMPLE_RATE, dtype=np.float32))            # carga + calentamiento
        t0 = time.monotonic()
        self._run(np.zeros(5 * SAMPLE_RATE, dtype=np.float32))
        log.info("Modelo listo (MLX). Un paso tarda ~%.2fs (ideal: menos de 1s).", time.monotonic() - t0)
        if self.prompt_text:
            log.info("Vocabulario activo")

    def _run(self, audio: np.ndarray, final: bool = True, previous: str = "") -> str:
        return self._pool.submit(self._transcribe_blocking, audio, previous).result()

    def _transcribe_blocking(self, audio: np.ndarray, previous: str = "") -> str:
        prompt = self.prompt_for(previous)
        if self.short:
            return self._short_blocking(audio, prompt)
        import mlx_whisper
        out = mlx_whisper.transcribe(
            audio.astype(np.float32),
            path_or_hf_repo=self.model,
            language=self.language,
            task="transcribe",
            temperature=0.0,                    # una sola pasada: sin reintentos (más rápido)
            condition_on_previous_text=False,   # cada frase es independiente
            initial_prompt=prompt or None,
            verbose=None,
        )
        return strip_prompt((out.get("text") or "").strip(), prompt)

    def _decode_ctx(self, audio: np.ndarray, ctx: int | None, max_tokens: int | None,
                    prompt: str) -> tuple[str, object]:
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
                without_timestamps=True, fp16=True, prompt=prompt or None))
        finally:
            m.dims.n_audio_ctx = full_ctx
        r = res[0] if isinstance(res, list) else res
        return strip_prompt((r.text or "").strip(), prompt), r

    def _short_blocking(self, audio: np.ndarray, prompt: str = "") -> str:
        """
        Contexto corto (como «audio_ctx» de whisper.cpp): procesa la duración real + 1 s en vez de 30 s.
        Su fallo típico son los bucles, así que si sale repetitiva o demasiado larga,
        se repite con el contexto completo (más lento, fiable).
        """
        secs = len(audio) / SAMPLE_RATE
        frames = int(secs * SAMPLE_RATE / 160) + 1
        max_tokens = int(secs * 7) + 12                 # ~4 tokens/s al hablar rápido, con margen
        text, r = self._decode_ctx(audio, (frames + 1) // 2 + 50, max_tokens, prompt)
        if r.no_speech_prob > 0.6 and r.avg_logprob < -1.0:      # silencio/ruido
            return ""
        if looks_broken(text, len(r.tokens), max_tokens):
            self.fallbacks += 1
            text, r = self._decode_ctx(audio, None, None, prompt)
            if r.no_speech_prob > 0.6 and r.avg_logprob < -1.0:
                return ""
        return text

    async def transcribe(self, audio: np.ndarray, final: bool = True, previous: str = "") -> str:
        async with self.lock:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._pool, self._transcribe_blocking, audio, previous)


class MockTranscriber(_Base):
    """
    Whisper simulado: no carga ningún modelo. Devuelve frases fijas que dicen cuánto audio
    recibió, y tarda `delay` segundos. Sirve para probar todo lo demás (cortes, protocolo,
    traducción, reparto) en cualquier ordenador y en la integración continua.
    """

    def __init__(self, delay: float = 0.0, beams: int = 1, context: str = "none"):
        super().__init__(beams, context)
        self.delay = delay
        self.calls = 0
        self.prompts: list[str] = []

    def _run(self, audio: np.ndarray, final: bool = True, previous: str = "") -> str:
        self.calls += 1
        self.prompts.append(self.prompt_for(previous))
        if self.delay:
            time.sleep(self.delay)
        secs = len(audio) / SAMPLE_RATE
        if secs < 0.3:
            return ""
        return f"Satz {self.calls} mit {secs:.1f} Sekunden."


def make_transcriber(engine: str, model: str, device: str | None, language: str, vocab: str = "",
                     audio_ctx: str = "full", beams: int = 1, context: str = "none"):
    if engine == "mock":
        return MockTranscriber(beams=beams, context=context)
    if engine == "mlx":
        return MlxTranscriber(model, language, vocab, audio_ctx, beams, context)
    return Transcriber(model, device, language, vocab, beams, context)
