"""
Traducción en el servidor con NLLB-200 (Meta), gratis y en este ordenador.

  - Un solo modelo traduce entre los 15 idiomas en cualquier dirección.
  - Corre en el procesador (CPU): la tarjeta gráfica queda libre para Whisper.
  - Motor rápido: CTranslate2 con el modelo convertido (bash tools/setup_nllb.sh).
    Si no está, se usa transformers (más lento) o se queda desactivado.
  - Licencia del modelo: CC BY-NC 4.0 → solo uso NO comercial (como el modelo suizo).

Antes de traducir: glosario bíblico (si existe para la pareja) y frases fijas litúrgicas.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

log = logging.getLogger("whisper-server")

HERE = Path(__file__).resolve().parent
GLOSSARY_DIR = HERE.parent / "web" / "glossary"
FIXED_FILE = HERE / "vocab" / "frases-fijas.json"
CT2_DIR = HERE / "models" / "nllb-600m-ct2"
HF_MODEL = "facebook/nllb-200-distilled-600M"

# Los 15 idiomas más hablados (Ethnologue 2026), código corto → código NLLB.
LANGUAGES: dict[str, tuple[str, str]] = {
    "en": ("eng_Latn", "inglés"),
    "zh": ("zho_Hans", "chino (simplificado)"),
    "hi": ("hin_Deva", "hindi"),
    "es": ("spa_Latn", "español"),
    "ar": ("arb_Arab", "árabe"),
    "fr": ("fra_Latn", "francés"),
    "bn": ("ben_Beng", "bengalí"),
    "pt": ("por_Latn", "portugués"),
    "id": ("ind_Latn", "indonesio"),
    "ur": ("urd_Arab", "urdu"),
    "ru": ("rus_Cyrl", "ruso"),
    "de": ("deu_Latn", "alemán"),
    "ja": ("jpn_Jpan", "japonés"),
    "mr": ("mar_Deva", "maratí"),
    "vi": ("vie_Latn", "vietnamita"),
}
# Otros que NLLB también cubre (por si los oyentes reales los necesitan)
EXTRA_LANGUAGES: dict[str, tuple[str, str]] = {
    "it": ("ita_Latn", "italiano"),
    "tr": ("tur_Latn", "turco"),
    "uk": ("ukr_Cyrl", "ucraniano"),
    "fa": ("pes_Arab", "persa"),
    "ti": ("tir_Ethi", "tigriña"),
    "pl": ("pol_Latn", "polaco"),
}
ALL_LANGUAGES = {**LANGUAGES, **EXTRA_LANGUAGES}
MAX_TARGETS = 15


def short_code(code: str) -> str:
    """de-CH → de, pt-BR → pt."""
    return (code or "").split("-")[0].lower()


def clean_targets(targets, src: str) -> list[str]:
    """Idiomas pedidos que se pueden traducir (sin repetir, sin el de origen, como mucho 15)."""
    out: list[str] = []
    for t in targets or []:
        t = short_code(str(t))
        if t in ALL_LANGUAGES and t != short_code(src) and t not in out:
            out.append(t)
    return out[:MAX_TARGETS]


# ---------------------------------------------------------------------------
# Glosario y frases fijas
# ---------------------------------------------------------------------------
class Glossary:
    """
    Mismo comportamiento que la página: antes de traducir, los términos del idioma de origen
    se sustituyen por su forma fija en el idioma de destino (nombres bíblicos, «Abendmahl» → «Santa Cena»).
    """

    def __init__(self, directory: Path = GLOSSARY_DIR):
        self.directory = directory
        self._cache: dict[str, tuple[re.Pattern | None, dict[str, str]]] = {}

    def _load(self, pair: str):
        if pair in self._cache:
            return self._cache[pair]
        a, b = pair.split(">")
        path = self.directory / f"{a}-{b}.json"
        entries: dict[str, str] = {}
        if path.exists():
            try:
                entries = json.loads(path.read_text(encoding="utf-8")).get("entries", {})
            except ValueError:
                log.warning("Glosario ilegible: %s", path)
        norm = {" ".join(k.lower().split()): v for k, v in entries.items()}
        keys = sorted(entries, key=len, reverse=True)
        pattern = None
        if keys:
            body = "|".join(re.escape(k).replace(r"\ ", r"\s+") for k in keys)
            pattern = re.compile(rf"(?<![\w])(?:{body})(?![\w])", re.IGNORECASE)
        self._cache[pair] = (pattern, norm)
        return self._cache[pair]

    def size(self, src: str, tgt: str) -> int:
        return len(self._load(f"{short_code(src)}>{short_code(tgt)}")[1])

    def apply(self, text: str, src: str, tgt: str) -> str:
        pattern, norm = self._load(f"{short_code(src)}>{short_code(tgt)}")
        if not pattern:
            return text
        return pattern.sub(lambda m: norm.get(" ".join(m.group(0).lower().split()), m.group(0)), text)


class FixedPhrases:
    """
    Frases litúrgicas que no deben pasar por el traductor («Amen.», «Halleluja!»).
    Solo se usan si la frase ENTERA es una de ellas. Los idiomas sin forma revisada
    se traducen normalmente (mejor eso que inventar una grafía).
    """

    def __init__(self, path: Path = FIXED_FILE):
        self.phrases: dict[str, dict[str, str]] = {}
        self.aliases: dict[str, str] = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, item in data.get("phrases", {}).items():
                self.phrases[key] = item.get("forms", {})
                for alias in item.get("match", []) + list(item.get("forms", {}).values()):
                    self.aliases[self._norm(alias)] = key

    @staticmethod
    def _norm(text: str) -> str:
        return re.sub(r"[\s.!?¡¿,;:«»\"'’]+", " ", text.lower()).strip()

    def lookup(self, text: str, tgt: str) -> str | None:
        key = self.aliases.get(self._norm(text))
        if not key:
            return None
        form = self.phrases.get(key, {}).get(short_code(tgt))
        if not form:
            return None
        end = text.strip()[-1:] if text.strip()[-1:] in ".!?" else ""
        return form + end


# ---------------------------------------------------------------------------
# Motores
# ---------------------------------------------------------------------------
class _Backend:
    name = "?"

    def translate_many(self, text: str, src: str, targets: list[str]) -> dict[str, str]:
        raise NotImplementedError


class Ct2Backend(_Backend):
    """CTranslate2 + modelo convertido a int8: el más rápido en procesador."""
    name = "nllb-ct2"

    def __init__(self, model_dir: Path, beams: int = 2, threads: int = 4):
        import ctranslate2
        from transformers import AutoTokenizer
        self.translator = ctranslate2.Translator(str(model_dir), device="cpu", compute_type="int8",
                                                 inter_threads=1, intra_threads=threads)
        self.tok = AutoTokenizer.from_pretrained(HF_MODEL)
        self.beams = beams

    def translate_many(self, text: str, src: str, targets: list[str]) -> dict[str, str]:
        self.tok.src_lang = ALL_LANGUAGES[src][0]
        source = self.tok.convert_ids_to_tokens(self.tok.encode(text))
        codes = [ALL_LANGUAGES[t][0] for t in targets]
        # Una sola llamada para todos los idiomas: se procesan juntos (lote)
        results = self.translator.translate_batch(
            [source] * len(codes), target_prefix=[[c] for c in codes],
            beam_size=self.beams, max_decoding_length=256, repetition_penalty=1.1)
        out = {}
        for t, code, r in zip(targets, codes, results):
            hyp = r.hypotheses[0]
            if hyp and hyp[0] == code:
                hyp = hyp[1:]
            out[t] = self.tok.decode(self.tok.convert_tokens_to_ids(hyp), skip_special_tokens=True).strip()
        return out


class HfBackend(_Backend):
    """transformers directamente: sin conversión, pero más lento. Reserva por si CTranslate2 falla."""
    name = "nllb-transformers"

    def __init__(self, beams: int = 2):
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        self.tok = AutoTokenizer.from_pretrained(HF_MODEL)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(HF_MODEL)
        self.model.eval()
        self.beams = beams

    def translate_many(self, text: str, src: str, targets: list[str]) -> dict[str, str]:
        import torch
        self.tok.src_lang = ALL_LANGUAGES[src][0]
        inputs = self.tok(text, return_tensors="pt")
        out = {}
        with torch.inference_mode():
            for t in targets:
                gen = self.model.generate(**inputs, num_beams=self.beams, max_new_tokens=256,
                                          forced_bos_token_id=self.tok.convert_tokens_to_ids(ALL_LANGUAGES[t][0]))
                out[t] = self.tok.batch_decode(gen, skip_special_tokens=True)[0].strip()
        return out


class FakeBackend(_Backend):
    """Para pruebas: «traduce» poniendo el idioma delante. No descarga nada."""
    name = "fake"

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.calls: list[tuple[str, str, list[str]]] = []

    def translate_many(self, text: str, src: str, targets: list[str]) -> dict[str, str]:
        self.calls.append((text, src, list(targets)))
        if self.delay:
            time.sleep(self.delay)
        return {t: f"[{t}] {text}" for t in targets}


def load_backend(kind: str = "auto", model_dir: Path = CT2_DIR, beams: int = 2, threads: int = 4) -> _Backend | None:
    """auto: CTranslate2 si está instalado y convertido; si no, ninguno (se avisa cómo activarlo)."""
    if kind == "off":
        return None
    if kind == "fake":
        return FakeBackend()
    if kind in ("auto", "ct2"):
        try:
            import ctranslate2  # noqa: F401
            if (model_dir / "model.bin").exists():
                return Ct2Backend(model_dir, beams, threads)
            msg = f"no está convertido el modelo NLLB en {model_dir}"
        except ImportError:
            msg = "falta ctranslate2"
        if kind == "ct2":
            raise SystemExit(f"Traducción NLLB: {msg}. Ejecuta una vez:  bash tools/setup_nllb.sh")
        log.info("Traducción en el servidor desactivada (%s). Para activarla: bash tools/setup_nllb.sh", msg)
        return None
    if kind == "transformers":
        return HfBackend(beams)
    raise ValueError(f"motor de traducción desconocido: {kind}")


class TranslationService:
    """
    Lo que usa el servidor: glosario + frases fijas + motor, en UN hilo propio
    (las frases salen en orden y Whisper nunca espera por la traducción).
    """

    def __init__(self, backend: _Backend, glossary: Glossary | None = None, fixed: FixedPhrases | None = None):
        self.backend = backend
        self.glossary = glossary or Glossary()
        self.fixed = fixed or FixedPhrases()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nllb")

    @property
    def name(self) -> str:
        return self.backend.name

    def translate_sync(self, text: str, src: str, targets: list[str]) -> dict[str, str]:
        src = short_code(src)
        targets = clean_targets(targets, src)
        if not text.strip() or not targets or src not in ALL_LANGUAGES:
            return {}
        out: dict[str, str] = {}
        # Frases fijas primero; el resto se agrupa por texto de entrada (el glosario lo cambia por destino)
        groups: dict[str, list[str]] = {}
        for t in targets:
            fixed = self.fixed.lookup(text, t)
            if fixed is not None:
                out[t] = fixed
                continue
            groups.setdefault(self.glossary.apply(text, src, t), []).append(t)
        for source_text, tgts in groups.items():
            out.update(self.backend.translate_many(source_text, src, tgts))
        return {t: out[t] for t in targets if t in out}

    async def translate(self, text: str, src: str, targets: list[str]) -> tuple[dict[str, str], float]:
        t0 = time.monotonic()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(self._pool, self.translate_sync, text, src, targets)
        return result, time.monotonic() - t0
