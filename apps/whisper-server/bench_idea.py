#!/usr/bin/env python3
"""
Mide en ESTE Mac cuánto tarda el modo idea y qué escribe, con frases de prédica de ejemplo.
Le pasa lo mismo que la página: el original con el glosario aplicado + la traducción literal.
Requisitos: Ollama abierto y el modelo descargado (ollama pull gemma3:4b).

  .venv/bin/python bench_idea.py                       # compara «original + literal» con «solo literal»
  .venv/bin/python bench_idea.py --model llama3.2:3b   # comparar con otro modelo sin razonamiento
Consejo: ejecútalo también con el servidor Whisper transcribiendo, para ver cómo se reparten el Mac.
"""
import argparse
import asyncio
import json
import re
import statistics
from pathlib import Path

from idea import IdeaClient

# (original, traducción literal como la de Chrome, idea que esperaría un intérprete)
CASOS = [
    ("Liebe Gemeinde, schön, dass ihr heute Morgen alle da seid.",
     "Querida iglesia, qué bien que estéis todos aquí esta mañana.",
     "Bienvenidos todos esta mañana."),
    ("Wir lesen heute aus dem Johannesevangelium, Kapitel drei, Vers sechzehn.",
     "Hoy leemos del Evangelio de Juan, capítulo tres, versículo dieciséis.",
     "Leemos Juan 3:16."),
    ("Denn so sehr hat Gott die Welt geliebt, dass er seinen einzigen Sohn gab.",
     "Porque de tal manera amó Dios al mundo, que dio a su Hijo unigénito.",
     "Dios amó tanto al mundo que dio a su único Hijo."),
    ("Und das heisst für uns ganz konkret: Wir müssen uns diese Liebe nicht verdienen.",
     "Y eso significa para nosotros muy concretamente: no tenemos que merecer este amor.",
     "No tenemos que merecer el amor de Dios."),
    ("Viele von uns denken, sie müssten zuerst perfekt sein, bevor Gott sie annimmt.",
     "Muchos de nosotros pensamos que primero tenemos que ser perfectos antes de que Dios nos acepte.",
     "Muchos creen que deben ser perfectos para que Dios los acepte."),
    ("Aber Paulus schreibt im Römerbrief, dass wir aus Gnade gerettet sind, nicht aus Werken.",
     "Pero Pablo escribe en la carta a los Romanos que somos salvos por gracia, no por obras.",
     "Pablo (Romanos): somos salvos por gracia, no por obras."),
    ("Das ist die gute Nachricht, das Evangelium, das wir heute feiern dürfen.",
     "Esta es la buena noticia, el evangelio, que hoy podemos celebrar.",
     "Esa es la buena noticia que celebramos hoy."),
    ("Lasst uns gemeinsam beten.", "Oremos juntos.", "Oremos juntos."),
]


def load_glossary():
    """El mismo glosario que usa la página (apps/web/glossary/de-es.json)."""
    path = Path(__file__).resolve().parent.parent / "web" / "glossary" / "de-es.json"
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
    except (OSError, ValueError, KeyError):
        return lambda t: t
    lookup = {" ".join(k.lower().split()): v for k, v in entries.items()}
    keys = sorted(entries, key=len, reverse=True)
    rx = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(k).replace(r"\ ", r"\s+") for k in keys) + r")(?!\w)",
                    re.IGNORECASE)
    return lambda t: rx.sub(lambda m: lookup.get(" ".join(m.group(0).lower().split()), m.group(0)), t)


async def run(client: IdeaClient, glossary, mode: str) -> list[dict]:
    results, context, context_lit = [], [], []
    for orig, literal, _esperado in CASOS:
        src = glossary(orig)
        r = await client.idea(context, src, "de", "es", literal, context_literal=context_lit, input_mode=mode)
        if r.get("reasoning"):
            raise SystemExit(f"\n✕ {r['error']}")
        context.append(src)
        context_lit.append(literal)
        results.append(r)
    return results


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma3:4b")
    ap.add_argument("--input", choices=("ambos", "literal", "comparar"), default="comparar",
                    help="Qué recibe el modelo; «comparar» prueba las dos formas")
    args = ap.parse_args()
    client = IdeaClient(args.model, timeout=60)
    st = await client.status()
    if not st["ok"]:
        print(st["message"])
        return
    glossary = load_glossary()
    modes = ["ambos", "literal"] if args.input == "comparar" else [args.input]
    print(f"Modelo {args.model}: cargando el modelo…")
    await client.idea([], "Hallo.", "de", "es", "Hola.")          # calentar: la primera llamada es lenta
    res = {m: await run(client, glossary, m) for m in modes}
    await client.close()

    labels = {"ambos": "original + literal", "literal": "solo literal"}
    for i, (orig, _lit, esperado) in enumerate(CASOS):
        print(f"\n{i + 1}. {orig}\n   ✓ esperado: {esperado}")
        for m in modes:
            r = res[m][i]
            print(f"   💡 {labels[m]:<18} {r['ms']:>5} ms  {r['idea'] or '(sin idea)'}")
    print()
    for m in modes:
        t = [r["ms"] for r in res[m]]
        print(f"{labels[m]:<20} típico {statistics.median(t) / 1000:.1f} s  (máx. {max(t) / 1000:.1f} s)")
    print("\nValora cada idea: ¿dice lo mismo que «esperado»? ¿inventa o se adelanta? ¿está vacía donde no debería?")
    if len(modes) == 2:
        print("Si «solo literal» es igual de fiel y más rápido, arranca el servidor con:  --idea-input literal")


if __name__ == "__main__":
    asyncio.run(main())
