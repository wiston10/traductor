#!/usr/bin/env python3
"""
Genera el glosario bíblico incorporado a partir de Biblias de dominio público
alineadas por versículo (descárgalas antes con tools/fetch_bibles.py).

Qué produce:
  apps/web/glossary/de-es.json, fr-es.json, en-es.json   -> glosario que usa la página
  apps/whisper-server/vocab/de.txt                        -> vocabulario para Whisper

Cómo funciona:
  1. Lista curada (libros de la Biblia y términos de iglesia), escrita a mano.
  2. Nombres propios extraídos automáticamente: se busca qué palabra del texto
     alemán/francés/inglés aparece SIEMPRE en los mismos versículos que cada nombre
     propio de la Reina-Valera (coeficiente de Dice). Solo se guardan parejas muy fiables.
  La lista curada manda sobre la automática.

Uso: python3 tools/build_glossary.py [--min-count 3] [--min-dice 0.6]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIBLES = ROOT / "data" / "bibles"
OUT_GLOSSARY = ROOT / "apps" / "web" / "glossary"
OUT_VOCAB = ROOT / "apps" / "whisper-server" / "vocab"

SOURCES = {
    "es": "Reina-Valera 1909",
    "de": "Elberfelder 1905",
    "fr": "Bible Crampon 1923",
    "en": "American Standard Version 1901",
}

WORD = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*", re.UNICODE)
# Grafías antiguas de la Reina-Valera 1909 (Achâb, Thare, Sophonías): mejor que el
# traductor ponga la forma moderna (Acab, Taré, Sofonías)
ARCHAIC_ES = re.compile(r"[âêîôû]|th|ph", re.IGNORECASE)
SENTENCE_START = re.compile(r"(^|[.:;!?¿¡«»\"“”(]\s*)$")

# Palabras españolas con mayúscula que NO son nombres que convenga forzar
# (el traductor ya las traduce bien y forzarlas empeora la gramática).
ES_STOP = {
    "Dios", "Señor", "Jehová", "Espíritu", "Santo", "Padre", "Hijo", "Rey", "Cristo",
    "Y", "E", "O", "Mas", "Porque", "Entonces", "Pues", "Así", "Mira", "He", "Oh",
    "Selah", "Aleluya", "Amén", "Día", "Noche", "Cielos", "Tierra",
}

# ---------------------------------------------------------------------------
# Lista curada: libros (solo formas no ambiguas) y términos de iglesia.
# Se omiten a propósito palabras que en el idioma de origen también son comunes
# (p. ej. alemán "Richter"=juez, "Prediger"=predicador; inglés "Mark", "Job", "Acts").
# ---------------------------------------------------------------------------
CURATED: dict[str, dict[str, str]] = {
    "de": {
        # Libros
        "Genesis": "Génesis", "Exodus": "Éxodo", "Levitikus": "Levítico", "Numeri": "Números",
        "Deuteronomium": "Deuteronomio", "Josua": "Josué", "Chronik": "Crónicas",
        "Esra": "Esdras", "Nehemia": "Nehemías", "Hiob": "Job", "Psalm": "Salmo", "Psalmen": "Salmos",
        "Sprüche Salomos": "Proverbios", "Hohelied": "Cantares", "Hohen Lied": "Cantares",
        "Jesaja": "Isaías", "Jeremia": "Jeremías", "Klagelieder": "Lamentaciones",
        "Hesekiel": "Ezequiel", "Ezechiel": "Ezequiel", "Hosea": "Oseas", "Amos": "Amós",
        "Obadja": "Abdías", "Jona": "Jonás", "Micha": "Miqueas", "Nahum": "Nahúm",
        "Habakuk": "Habacuc", "Zefanja": "Sofonías", "Haggai": "Hageo", "Sacharja": "Zacarías",
        "Maleachi": "Malaquías", "Matthäus": "Mateo", "Matthäusevangelium": "Evangelio de Mateo",
        "Markus": "Marcos", "Markusevangelium": "Evangelio de Marcos", "Lukas": "Lucas",
        "Lukasevangelium": "Evangelio de Lucas", "Johannes": "Juan",
        "Johannesevangelium": "Evangelio de Juan", "Apostelgeschichte": "Hechos de los Apóstoles",
        "Römerbrief": "Epístola a los Romanos", "Römer": "Romanos", "Korinther": "Corintios",
        "Korintherbrief": "Epístola a los Corintios", "Galater": "Gálatas", "Epheser": "Efesios",
        "Philipper": "Filipenses", "Kolosser": "Colosenses", "Thessalonicher": "Tesalonicenses",
        "Timotheus": "Timoteo", "Titus": "Tito", "Philemon": "Filemón", "Hebräer": "Hebreos",
        "Hebräerbrief": "Epístola a los Hebreos", "Jakobusbrief": "Epístola de Santiago",
        "Petrus": "Pedro", "Petrusbrief": "Epístola de Pedro", "Offenbarung des Johannes": "Apocalipsis",
        "Mose": "Moisés",
        # Iglesia (con variantes por declinación)
        "Heiliger Geist": "Espíritu Santo", "Heilige Geist": "Espíritu Santo",
        "Heiligen Geist": "Espíritu Santo", "Heiligen Geistes": "Espíritu Santo",
        "Jesus Christus": "Jesucristo", "Jesu Christi": "Jesucristo",
        "Abendmahl": "Santa Cena", "Gottesdienst": "culto", "Lobpreis": "alabanza",
        "Gemeinde": "iglesia", "Bergpredigt": "Sermón del Monte", "Vaterunser": "Padre Nuestro",
        "Pfingsten": "Pentecostés", "Ostern": "Pascua", "Karfreitag": "Viernes Santo",
        "Auferstehung": "resurrección", "Buße": "arrepentimiento", "Busse": "arrepentimiento",
    },
    "fr": {
        "Genèse": "Génesis", "Exode": "Éxodo", "Lévitique": "Levítico", "Deutéronome": "Deuteronomio",
        "Josué": "Josué", "Chroniques": "Crónicas", "Néhémie": "Nehemías", "Psaume": "Salmo",
        "Psaumes": "Salmos", "Proverbes": "Proverbios", "Ecclésiaste": "Eclesiastés",
        "Cantique des cantiques": "Cantares", "Ésaïe": "Isaías", "Esaïe": "Isaías", "Isaïe": "Isaías",
        "Jérémie": "Jeremías", "Lamentations": "Lamentaciones", "Ézéchiel": "Ezequiel",
        "Ezéchiel": "Ezequiel", "Osée": "Oseas", "Abdias": "Abdías", "Jonas": "Jonás",
        "Michée": "Miqueas", "Sophonie": "Sofonías", "Aggée": "Hageo", "Zacharie": "Zacarías",
        "Malachie": "Malaquías", "Matthieu": "Mateo", "Luc": "Lucas", "Jean": "Juan",
        "Actes des apôtres": "Hechos de los Apóstoles", "Romains": "Romanos", "Corinthiens": "Corintios",
        "Galates": "Gálatas", "Éphésiens": "Efesios", "Ephésiens": "Efesios", "Philippiens": "Filipenses",
        "Colossiens": "Colosenses", "Thessaloniciens": "Tesalonicenses", "Timothée": "Timoteo",
        "Tite": "Tito", "Philémon": "Filemón", "Hébreux": "Hebreos", "Apocalypse": "Apocalipsis",
        "Moïse": "Moisés",
        "Saint-Esprit": "Espíritu Santo", "Esprit Saint": "Espíritu Santo", "Sainte Cène": "Santa Cena",
        "Jésus-Christ": "Jesucristo", "Pentecôte": "Pentecostés", "Notre Père": "Padre Nuestro",
        "Sermon sur la montagne": "Sermón del Monte",
    },
    "en": {
        "Genesis": "Génesis", "Exodus": "Éxodo", "Leviticus": "Levítico", "Deuteronomy": "Deuteronomio",
        "Joshua": "Josué", "Chronicles": "Crónicas", "Ezra": "Esdras", "Nehemiah": "Nehemías",
        "Psalm": "Salmo", "Psalms": "Salmos", "Proverbs": "Proverbios", "Ecclesiastes": "Eclesiastés",
        "Song of Solomon": "Cantares", "Song of Songs": "Cantares", "Isaiah": "Isaías",
        "Jeremiah": "Jeremías", "Lamentations": "Lamentaciones", "Ezekiel": "Ezequiel", "Hosea": "Oseas",
        "Obadiah": "Abdías", "Jonah": "Jonás", "Micah": "Miqueas", "Habakkuk": "Habacuc",
        "Zephaniah": "Sofonías", "Haggai": "Hageo", "Zechariah": "Zacarías", "Malachi": "Malaquías",
        "Matthew": "Mateo", "Luke": "Lucas", "Romans": "Romanos", "Corinthians": "Corintios",
        "Galatians": "Gálatas", "Ephesians": "Efesios", "Philippians": "Filipenses",
        "Colossians": "Colosenses", "Thessalonians": "Tesalonicenses", "Timothy": "Timoteo",
        "Titus": "Tito", "Philemon": "Filemón", "Hebrews": "Hebreos", "Moses": "Moisés",
        "Holy Spirit": "Espíritu Santo", "Holy Ghost": "Espíritu Santo", "Lord's Supper": "Santa Cena",
        "Jesus Christ": "Jesucristo", "Pentecost": "Pentecostés", "Lord's Prayer": "Padre Nuestro",
        "Sermon on the Mount": "Sermón del Monte",
    },
}


# Errores detectados al revisar a mano (nombres que siempre aparecen juntos en listas)
BLACKLIST = {
    "de": {"Gideonis", "Kiljon"},
    "fr": {"Ahicam", "Romélie", "Chypre"},
    "en": {"Gideoni"},
}
# Formas modernas preferidas sobre la Reina-Valera 1909
MODERN = {
    "de": {"Epheser": "Efesios", "Ephesus": "Éfeso", "Zypern": "Chipre"},
    "fr": {"Marie-Madeleine": "María Magdalena", "Jean-Baptiste": "Juan el Bautista", "Ephèse": "Éfeso"},
    "en": {"Ephesus": "Éfeso", "Cyprus": "Chipre"},
}


def load(lang: str) -> dict[tuple[str, int, int], str]:
    path = BIBLES / f"{lang}.csv"
    if not path.exists():
        sys.exit(f"Falta {path}. Ejecuta antes: python3 tools/fetch_bibles.py")
    verses = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            try:
                verses[(row["Book"], int(row["Chapter"]), int(row["Verse"]))] = row["Text"]
            except (KeyError, ValueError):
                continue
    return verses


def capitalized_tokens(text: str, skip_sentence_start: bool) -> list[str]:
    out = []
    for m in WORD.finditer(text):
        w = m.group(0)
        if not w[0].isupper() or len(w) < 2 or w.isupper():
            continue
        if skip_sentence_start and SENTENCE_START.search(text[: m.start()]):
            continue
        out.append(w)
    return out


def case_stats(verses: dict) -> tuple[Counter, Counter]:
    """Cuántas veces aparece cada palabra con mayúscula y en minúscula."""
    upper, lower = Counter(), Counter()
    for t in verses.values():
        for m in WORD.finditer(t):
            w = m.group(0)
            (upper if w[0].isupper() else lower)[w.lower()] += 1
    return upper, lower


def is_common_word(word: str, upper: Counter, lower: Counter) -> bool:
    """Palabra que también es común en minúscula (p. ej. francés 'Pierre'/'pierre')."""
    lw = word.lower()
    return lower[lw] > 0.2 * max(1, upper[lw])


def similarity(a: str, b: str) -> float:
    """Parecido de escritura sin acentos (Jesaja/Isaías, David/David)."""
    norm = lambda w: "".join(c for c in unicodedata.normalize("NFD", w.lower()) if not unicodedata.combining(c))
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def align(es: dict, src: dict, lang: str, min_count: int, min_dice: float) -> dict[str, tuple[str, float, int]]:
    """Empareja nombres propios españoles con su forma en el otro idioma."""
    es_upper, es_lower = case_stats(es)
    src_upper, src_lower = case_stats(src)

    f_es, f_src, co = Counter(), Counter(), defaultdict(Counter)
    for key, es_text in es.items():
        src_text = src.get(key)
        if not src_text:
            continue
        names = {w for w in capitalized_tokens(es_text, True)
                 if w not in ES_STOP and not is_common_word(w, es_upper, es_lower)}
        # En alemán todos los sustantivos van en mayúscula: no se puede saltar el inicio de frase igual
        cands = set(capitalized_tokens(src_text, lang != "de"))
        for n in names:
            f_es[n] += 1
        for c in cands:
            f_src[c] += 1
        for n in names:
            for c in cands:
                co[n][c] += 1

    # Candidatas: para cada nombre, sus 3 mejores palabras de origen
    def score(name: str, src_word: str, c: int) -> tuple[float, float]:
        dice = 2 * c / (f_es[name] + f_src[src_word])
        # Un poco de parecido de escritura deshace empates (David / Jerusalén siempre juntos)
        return dice + 0.15 * similarity(name, src_word), dice

    candidates = []
    for name, fn in f_es.items():
        if fn < min_count:
            continue
        ranked = sorted(co[name].items(), key=lambda kv: -score(name, kv[0], kv[1])[0])[:3]
        for src_word, c in ranked:
            sc, dice = score(name, src_word, c)
            if dice < min_dice or c < min_count:
                continue
            if lang != "de" and is_common_word(src_word, src_upper, src_lower):
                continue
            candidates.append((sc, dice, c, name, src_word))

    # Emparejamiento uno a uno, de la pareja más fiable a la menos fiable
    result: dict[str, tuple[str, float, int]] = {}
    used_names: set[str] = set()
    for sc, dice, c, name, src_word in sorted(candidates, reverse=True):
        if name in used_names or src_word in result:
            continue
        used_names.add(name)
        result[src_word] = (name, dice, c)
    return result


def cross_checked(lang: str, auto: dict, others: dict[str, dict]) -> tuple[dict, list]:
    """
    Acepta (origen -> español) solo si el origen se parece por escritura al español o a la
    forma del mismo nombre en otro idioma (p. ej. alemán 'Zeruja' ~ inglés 'Zeruiah').
    Elimina sustantivos comunes emparejados por casualidad ('Zwilling' -> 'Dídimo').
    """
    forms_by_es: dict[str, list[str]] = defaultdict(list)
    for olang, oauto in others.items():
        for osrc, (oes, _d, _c) in oauto.items():
            forms_by_es[oes].append(osrc)
    kept, rejected = {}, []
    for src, (es_name, dice, c) in auto.items():
        best = max([similarity(src, es_name)] + [similarity(src, f) for f in forms_by_es.get(es_name, [])])
        if best >= 0.5:
            kept[src] = (es_name, dice, c)
        else:
            rejected.append(f"{src}→{es_name}")
    return kept, rejected


def build(min_count: int, min_dice: float) -> None:
    es = load("es")
    OUT_GLOSSARY.mkdir(parents=True, exist_ok=True)
    OUT_VOCAB.mkdir(parents=True, exist_ok=True)
    langs = ("de", "fr", "en")
    raw = {lang: align(es, load(lang), lang, min_count, min_dice) for lang in langs}
    for lang in langs:
        auto, rejected = cross_checked(lang, raw[lang], {o: raw[o] for o in langs if o != lang})
        entries: dict[str, str] = {}
        same = archaic = 0
        for s, (t, _dice, _c) in sorted(auto.items(), key=lambda kv: -kv[1][2]):
            if s in BLACKLIST[lang]:
                continue
            if s == t:
                same += 1          # igual en los dos idiomas: no hace falta traducir
                continue
            if ARCHAIC_ES.search(t):
                archaic += 1
                continue
            entries[s] = t
        n_auto = len(entries)
        entries.update(MODERN[lang])
        entries.update(CURATED[lang])   # lo curado manda
        data = {
            "pair": f"{lang}>es",
            "generated": date.today().isoformat(),
            "sources": [SOURCES[lang], SOURCES["es"]],
            "note": "Generado con tools/build_glossary.py. Textos de dominio público.",
            "entries": dict(sorted(entries.items(), key=lambda kv: kv[0].lower())),
        }
        out = OUT_GLOSSARY / f"{lang}-es.json"
        out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{lang}>es: {len(entries)} términos ({n_auto} automáticos + {len(CURATED[lang])} curados; "
              f"descartados: {len(rejected)} dudosos, {archaic} con grafía antigua, {same} iguales)")

        if lang == "de":
            # Vocabulario para Whisper: iglesia + libros + nombres más frecuentes (< ~200 tokens)
            names = [s for s, _ in sorted(auto.items(), key=lambda kv: -kv[1][2])][:70]
            books = ["Matthäus", "Markus", "Lukas", "Johannes", "Apostelgeschichte", "Römer",
                     "Korinther", "Galater", "Epheser", "Philipper", "Kolosser", "Hebräer",
                     "Offenbarung", "Jesaja", "Jeremia", "Hesekiel", "Psalmen", "Sprüche"]
            church = ["Jesus Christus", "Heiliger Geist", "Abendmahl", "Gnade", "Erlösung",
                      "Evangelium", "Gemeinde", "Gottesdienst", "Predigt", "Halleluja", "Amen"]
            seen, words = set(), []
            for w in church + books + names:
                if w not in seen:
                    seen.add(w)
                    words.append(w)
            vocab = "Predigt im Gottesdienst. " + ", ".join(words) + "."
            (OUT_VOCAB / "de.txt").write_text(vocab + "\n", encoding="utf-8")
            print(f"   vocabulario Whisper: {len(words)} términos -> {(OUT_VOCAB / 'de.txt').relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-count", type=int, default=3, help="Apariciones mínimas de un nombre")
    ap.add_argument("--min-dice", type=float, default=0.6, help="Fiabilidad mínima del emparejamiento (0–1)")
    args = ap.parse_args()
    build(args.min_count, args.min_dice)


if __name__ == "__main__":
    main()
