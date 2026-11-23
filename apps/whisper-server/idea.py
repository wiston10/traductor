"""
«Modo idea»: un LLM local (Ollama) resume en UNA frase corta en español la idea
de lo que acaba de decir el predicador, teniendo en cuenta lo dicho antes.

No sustituye a la traducción literal: va al lado, para que el intérprete capte la idea
de un vistazo y la diga con sus palabras.

Requisitos (una vez):  instalar Ollama (https://ollama.com) y  `ollama pull gemma3:4b`
Usa un modelo SIN razonamiento («thinking»): esos piensan en voz alta antes de responder,
tardan mucho más y no sirven en directo.
"""
from __future__ import annotations

import asyncio
import re
import time

import aiohttp

OLLAMA = "http://127.0.0.1:11434"
LANG_NAMES = {"de": "alemán", "fr": "francés", "en": "inglés", "es": "español", "it": "italiano", "pt": "portugués"}

_RULES = (
    "Escribe UNA frase en {tgt}, natural y gramaticalmente correcta, de como máximo {max_words} palabras, "
    "que CONDENSE fielmente lo que dice ese fragmento, para que el intérprete lo diga de un vistazo. "
    "Reglas: usa solo lo que se dice en el fragmento (el contexto anterior es solo para entenderlo); "
    "no inventes ni interpretes; NO te adelantes a la conclusión del predicador: si cuenta lo que "
    "otros piensan o dicen, mantenlo como opinión de ellos; "
    "si se cita la Biblia escribe la referencia abreviada (p. ej. «Juan 3:16») y quién habla si se dice; "
    "conserva los nombres propios. Responde «…» SOLO si el fragmento no tiene contenido "
    "(muletilla, frase cortada). Responde únicamente con la frase."
)
SYSTEM_BOTH = (
    "Ayudas a un intérprete que traduce EN DIRECTO una prédica cristiana al {tgt}. "
    "Te doy el último fragmento del predicador (en {src}) y una traducción automática literal, "
    "que puede tener pequeños errores. " + _RULES
)
SYSTEM_LITERAL = (
    "Ayudas a un intérprete que traduce EN DIRECTO una prédica cristiana al {tgt}. "
    "Te doy una traducción automática literal al {tgt} del último fragmento del predicador, "
    "que puede tener pequeños errores. " + _RULES
)
SYSTEM = SYSTEM_BOTH  # compatibilidad

# Ejemplos (con frases distintas a las del banco de pruebas): enseñan el formato
# mucho mejor que las reglas a un modelo pequeño.
EXAMPLES = [
    ("Wir lesen heute aus dem Römerbrief, Kapitel acht, Vers achtundzwanzig.",
     "Hoy leemos de la carta a los Romanos, capítulo ocho, versículo veintiocho.",
     "Leemos Romanos 8:28."),
    ("Und wisst ihr, das ist eigentlich das Schöne daran, dass Gott uns nicht vergisst, "
     "auch wenn wir ihn manchmal vergessen.",
     "Y sabéis, eso es en realidad lo bonito, que Dios no nos olvida, aunque a veces nosotros lo olvidemos.",
     "Dios no nos olvida, aunque nosotros lo olvidemos."),
    # No adelantar conclusiones: lo que "otros piensan" sigue siendo opinión de otros
    ("Viele sagen: Ich muss zuerst mein Leben in Ordnung bringen, bevor ich zu Gott kommen kann.",
     "Muchos dicen: primero tengo que poner mi vida en orden antes de poder venir a Dios.",
     "Muchos creen que deben ordenar su vida antes de venir a Dios."),
    ("Ähm, ja, also, wo war ich?", "Eh, sí, bueno, ¿dónde estaba?", "…"),
]
INPUT_MODES = ("ambos", "literal")


def build_messages(context: list[str], latest: str, src: str, tgt: str,
                   literal: str = "", max_words: int = 16, input_mode: str = "literal",
                   context_literal: list[str] | None = None) -> list[dict]:
    """
    input_mode="literal": solo la traducción literal (por defecto; más fiel con modelos pequeños:
                          condensar español es más fácil que entender alemán y resumir a la vez)
    input_mode="ambos":   original + traducción literal
    Si no hay traducción literal (mismo idioma, traductor no disponible) se usa el original.
    """
    names = dict(src=LANG_NAMES.get(src, src), tgt=LANG_NAMES.get(tgt, tgt), max_words=max_words)
    only_lit = input_mode == "literal" and literal.strip()
    msgs = [{"role": "system", "content": (SYSTEM_LITERAL if only_lit else SYSTEM_BOTH).format(**names)}]
    if src == "de" and tgt == "es":                       # los ejemplos están en alemán → español
        for ex_src, ex_lit, ex_out in EXAMPLES:
            content = _user([], ex_lit, "") if only_lit else _user([], ex_src, ex_lit)
            msgs.append({"role": "user", "content": content})
            msgs.append({"role": "assistant", "content": ex_out})
    if only_lit:
        ctx = context_literal if context_literal else context
        msgs.append({"role": "user", "content": _user(ctx, literal, "")})
    else:
        msgs.append({"role": "user", "content": _user(context, latest, literal)})
    return msgs


def _user(context: list[str], latest: str, literal: str) -> str:
    ctx = "\n".join(f"- {c}" for c in context[-4:] if c.strip()) or "(sin contexto)"
    out = f"Contexto anterior:\n{ctx}\n\nÚltimo fragmento:\n{latest.strip()}"
    if literal.strip() and literal.strip() != latest.strip():
        out += f"\n\nTraducción literal:\n{literal.strip()}"
    return out


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
# Inicio típico de un modelo que "razona en voz alta" (casi siempre en inglés)
_REASONING = re.compile(
    r"^\s*(okay|ok,|alright|let'?s|let me|first,|so,|hmm|the user|i need|we need|i should|i'll)\b",
    re.IGNORECASE)


def is_reasoning(text: str) -> bool:
    """¿La respuesta es el razonamiento del modelo y no la frase pedida?"""
    t = (text or "").strip()
    return bool(_REASONING.match(t)) or t.lower().startswith("<think>")


def clean_output(text: str, max_words: int = 16) -> str:
    """Quita razonamientos, comillas y prefijos; recorta si el modelo se alarga."""
    t = text or ""
    if "</think>" in t.lower():                         # algunos modelos solo cierran la etiqueta
        t = t[t.lower().rfind("</think>") + len("</think>"):]
    t = _THINK.sub("", t).strip()
    if is_reasoning(t):
        return ""
    t = t.splitlines()[0].strip() if t else ""
    t = t.strip(" \"'«»“”`*")
    t = re.sub(r"^(idea( principal)?|frase|respuesta)\s*:\s*", "", t, flags=re.IGNORECASE)
    t = t.strip(" \"'«»“”`*")
    if re.fullmatch(r"[.…\s]*", t):                    # «...», «…», «.» = sin idea
        return ""
    words = t.split()
    if len(words) > max_words + 4:                      # margen: no cortar por una palabra
        t = " ".join(words[:max_words]) + "…"
    return t


class IdeaClient:
    def __init__(self, model: str, base: str = OLLAMA, timeout: float = 10.0, input_mode: str = "literal"):
        self.model = model
        # «literal» por defecto: en las pruebas con gemma3:4b fue más fiel (7/8 frente a 5/8)
        self.input_mode = input_mode if input_mode in INPUT_MODES else "literal"
        self.base = base
        self.timeout = timeout
        self.lock = asyncio.Lock()          # una petición a la vez: no competir con Whisper
        self._session: aiohttp.ClientSession | None = None

    async def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
        return self._session

    async def status(self) -> dict:
        """¿Está Ollama arrancado y el modelo descargado?"""
        try:
            http = await self._http()
            async with http.get(f"{self.base}/api/tags") as r:
                data = await r.json()
        except Exception:  # noqa: BLE001
            return {"ok": False, "model": self.model,
                    "message": "Ollama no está arrancado. Ábrelo (o ejecuta «ollama serve»)."}
        names = {m.get("name", "") for m in data.get("models", [])}
        installed = self.model in names or f"{self.model}:latest" in names
        return {"ok": installed, "model": self.model,
                "message": "" if installed else f"Falta el modelo. Ejecuta: ollama pull {self.model}"}

    async def idea(self, context: list[str], latest: str, src: str, tgt: str, literal: str = "",
                   context_literal: list[str] | None = None, input_mode: str | None = None) -> dict:
        if self.lock.locked():
            return {"busy": True}
        async with self.lock:
            body = {
                "model": self.model,
                "messages": build_messages(context, latest, src, tgt, literal,
                                           input_mode=input_mode or self.input_mode,
                                           context_literal=context_literal),
                "stream": False,
                "keep_alive": "30m",        # mantener el modelo cargado durante el culto
                "options": {"temperature": 0.2, "num_predict": 48, "num_ctx": 2048},
            }
            if self.model.startswith("qwen3"):
                body["think"] = False       # sin "pensar en voz alta": mucho más rápido
            t0 = time.monotonic()
            http = await self._http()
            async with http.post(f"{self.base}/api/chat", json=body) as r:
                if r.status != 200:
                    raise RuntimeError(f"Ollama respondió {r.status}: {(await r.text())[:200]}")
                data = await r.json()
            ms = round((time.monotonic() - t0) * 1000)
            raw = data.get("message", {}).get("content", "")
            text = clean_output(raw)
            if not text and (is_reasoning(raw) or data.get("message", {}).get("thinking")):
                return {"idea": "", "ms": ms, "reasoning": True,
                        "error": f"El modelo {self.model} razona en voz alta y no sirve en directo. "
                                 "Usa uno sin razonamiento, p. ej.: ollama pull gemma3:4b"}
            return {"idea": text, "ms": ms}

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
