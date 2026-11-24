#!/usr/bin/env python3
"""Pruebas de la traducción (sin descargar el modelo NLLB: motor simulado)."""
import asyncio

import translate as T


def test_quince_idiomas():
    assert len(T.LANGUAGES) == 15
    assert "de" in T.LANGUAGES and "es" in T.LANGUAGES and "zh" in T.LANGUAGES
    assert all("_" in code for code, _name in T.ALL_LANGUAGES.values())


def test_idiomas_pedidos():
    # Sin el de origen, sin repetidos, sin desconocidos, con variantes de región
    assert T.clean_targets(["es", "de", "es", "xx", "pt-BR", "EN"], "de-CH") == ["es", "pt", "en"]
    assert T.clean_targets(list(T.LANGUAGES), "es") == [c for c in T.LANGUAGES if c != "es"]
    assert len(T.clean_targets(list(T.ALL_LANGUAGES), "de")) == T.MAX_TARGETS


def test_glosario_biblico():
    g = T.Glossary()
    assert g.size("de", "es") > 100                       # el glosario generado de las Biblias
    out = g.apply("Wir feiern heute das Abendmahl.", "de", "es")
    assert "Santa Cena" in out
    assert g.apply("Wir feiern heute das Abendmahl.", "de", "zh") == "Wir feiern heute das Abendmahl."   # sin glosario
    assert g.size("es", "de") == 0


def test_frases_fijas():
    f = T.FixedPhrases()
    assert f.lookup("Amen.", "es") == "Amén."
    assert f.lookup("amen", "pt") == "Amém"
    assert f.lookup("Halleluja!", "en") == "Hallelujah!"
    assert f.lookup("Amen.", "zh") is None                # sin forma revisada: se traduce normal
    assert f.lookup("Amen, so sei es.", "es") is None     # solo si la frase entera es la fórmula


def test_servicio_con_motor_simulado():
    fake = T.FakeBackend()
    svc = T.TranslationService(fake)
    out = svc.translate_sync("Wir feiern das Abendmahl.", "de-CH", ["es", "en", "de", "zh"])
    assert list(out) == ["es", "en", "zh"]                 # el alemán es el original: no se traduce
    assert out["es"] == "[es] Wir feiern das Santa Cena."  # glosario aplicado solo hacia el español
    assert out["en"] == "[en] Wir feiern das Abendmahl."
    # en y zh comparten texto de entrada: UNA llamada para los dos (lote)
    assert len(fake.calls) == 2 and sorted(fake.calls[1][2]) == ["en", "zh"]
    amen = svc.translate_sync("Amen.", "de", ["es", "zh"])
    assert amen["es"] == "Amén." and amen["zh"] == "[zh] Amen."
    assert svc.translate_sync("", "de", ["es"]) == {}
    assert svc.translate_sync("Hallo", "de", []) == {}


def test_servicio_asincrono_en_orden():
    svc = T.TranslationService(T.FakeBackend(delay=0.01))

    async def run():
        res = await asyncio.gather(*(svc.translate(f"Satz {i}", "de", ["es"]) for i in range(5)))
        return [r[0]["es"] for r in res]
    assert asyncio.run(run()) == [f"[es] Satz {i}" for i in range(5)]


def test_sin_nllb_instalado_queda_desactivado():
    assert T.load_backend("off") is None
    assert T.load_backend("fake").name == "fake"
    # «auto» sin el modelo convertido: desactivada, sin romper el arranque
    from pathlib import Path
    assert T.load_backend("auto", model_dir=Path("/no/existe")) is None
