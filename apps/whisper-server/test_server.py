#!/usr/bin/env python3
"""Pruebas rápidas (sin modelos ni aiohttp). Uso: python3 run_tests.py  (o este archivo solo)"""
import numpy as np

import asr
import net
import segmenter

# Nombres de siempre, ahora repartidos en módulos
class s:  # noqa: N801
    Segmenter = segmenter.Segmenter
    origin_allowed = staticmethod(net.origin_allowed)
    strip_prompt = staticmethod(asr.strip_prompt)
    echoes_prompt = staticmethod(asr.echoes_prompt)
    looks_broken = staticmethod(asr.looks_broken)
    resolve_mlx_model = staticmethod(asr.resolve_mlx_model)
    MLX_SWISS_PATH = asr.MLX_SWISS_PATH
    DEFAULT_MODEL = asr.DEFAULT_MODEL

SR = 16000
rng = np.random.default_rng(0)


def voice(sec, amp=0.2):
    t = np.arange(int(sec * SR)) / SR
    return (amp * np.sin(2 * np.pi * 200 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t))).astype(np.float32)


def sil(sec):
    return rng.normal(0, 0.0008, int(sec * SR)).astype(np.float32)


def run(audio):
    seg = s.Segmenter(1.0, 0.5, 6.0)
    now, finals = 0.0, []
    for i in range(0, len(audio), 1600):
        seg.add((audio[i:i + 1600] * 32767).astype(np.int16).tobytes())
        now += 0.1
        kind, a = seg.decide(now)
        if kind == "final":
            finals.append(len(a) / SR)
    return finals, seg


def test_frases_con_pausa():
    finals, _ = run(np.concatenate([sil(1), voice(2), sil(1), voice(3), sil(1)]))
    assert len(finals) == 2, finals


def test_tos_se_descarta():
    finals, _ = run(np.concatenate([sil(1), voice(0.12), sil(1), voice(2), sil(1)]))
    assert len(finals) == 1, finals


def test_voz_floja_se_detecta():
    finals, _ = run(np.concatenate([sil(1), voice(2, amp=0.012), sil(1)]))
    assert len(finals) == 1, finals


def test_sin_pausas_corta_a_tiempo():
    finals, _ = run(np.concatenate([sil(1), voice(20)]))
    assert len(finals) >= 2 and all(f <= 6.01 for f in finals), finals


def test_sin_texto_provisional():
    seg = s.Segmenter(0, 0.5, 6.0)                 # --partial-every 0
    audio = np.concatenate([sil(0.5), voice(3), sil(1)])
    kinds = []
    now = 0.0
    for i in range(0, len(audio), 1600):
        seg.add((audio[i:i + 1600] * 32767).astype(np.int16).tobytes())
        now += 0.1
        k, _ = seg.decide(now)
        if k:
            kinds.append(k)
    assert kinds == ["final"], kinds


def test_no_provisional_si_la_frase_acaba():
    seg = s.Segmenter(1.0, 0.5, 6.0)
    seg.add((np.concatenate([sil(0.3), voice(2), sil(0.3)]) * 32767).astype(np.int16).tobytes())
    k, _ = seg.decide(10.0)                        # 0,3 s de pausa al final: la frase está acabando
    assert k is None, k


def test_flush():
    _, seg = run(np.concatenate([sil(0.5), voice(2.0)]))
    assert seg.flush() is not None and seg.seconds == 0
    _, seg = run(sil(1.0))
    assert seg.flush() is None


def test_origenes():
    assert s.origin_allowed(None, []) and s.origin_allowed("null", [])
    assert s.origin_allowed("http://localhost:8765", [])
    assert not s.origin_allowed("https://evil.example", [])
    assert not s.origin_allowed("http://localhost.evil.example", [])
    assert s.origin_allowed("https://x.github.io", ["https://x.github.io"])


def test_vocabulario():
    vocab = "Predigt im Gottesdienst. Jesus Christus, Heiliger Geist, Johannes, Petrus, Paulus."
    # Si transformers devuelve el vocabulario delante, se quita
    assert s.strip_prompt(vocab + " Heute lesen wir Johannes.", vocab) == "Heute lesen wir Johannes."
    assert s.strip_prompt("Heute lesen wir.", vocab) == "Heute lesen wir."
    # Whisper "leyendo" la lista en el silencio: se descarta
    assert s.echoes_prompt("Johannes, Petrus, Paulus.", vocab)
    # Una frase normal que menciona nombres de la lista: NO se descarta
    assert not s.echoes_prompt("Heute lesen wir, was Petrus und Johannes sagten.", vocab)
    assert not s.echoes_prompt("Johannes und Petrus", "")


def test_almacen_entrenamiento():
    import tempfile
    from pathlib import Path
    import training_store as ts
    root = Path(tempfile.mkdtemp()) / "training-data"
    rec = ts.Recorder(root)
    rec.save(voice(2), "Heute lesen wir Johannes.")
    rec.save(voice(1), "Musik")
    sid = rec.dir.name
    ts.update_segment(root, sid, "000001", "Heute lesen wir im Johannesevangelium.", "corrected")
    ts.update_segment(root, sid, "000002", None, "discarded")
    info = ts.get_session(root, sid)
    assert info["done"] == 1 and info["discarded"] == 1 and info["pending"] == 0
    assert info["items"][0]["auto_text"] == "Heute lesen wir Johannes."     # se conserva el original
    for bad_sid, bad_seg in (("../etc", "000001"), (sid, "../x")):
        try:
            ts.update_segment(root, bad_sid, bad_seg, "x", "ok")
            raise AssertionError("debería rechazar rutas peligrosas")
        except (ValueError, FileNotFoundError):
            pass
    assert ts.word_errors("Heute lesen wir im Evangelium.", "heute lesen wir in evangelium") == (1, 5)
    assert ts.word_errors("Er heißt Paulus", "er heisst paulus") == (0, 3)


def test_modo_idea():
    import idea
    m = idea.build_messages(["a", "b", "c", "d", "e"], "Gott liebt die Welt.", "de", "es", input_mode="ambos")
    assert "alemán" in m[0]["content"] and "español" in m[0]["content"]
    assert m[-1]["content"].count("\n- ") == 4                      # solo 4 frases de contexto
    assert len(m) == 10                                               # sistema + 4 ejemplos + pregunta
    lit = idea.build_messages(["Gott liebt uns."], "Darum gab er seinen Sohn.", "de", "es",
                              "Por eso dio a su Hijo.", input_mode="literal", context_literal=["Dios nos ama."])
    assert all("Darum" not in x["content"] and "Wir lesen" not in x["content"] for x in lit)   # sin alemán
    assert "- Dios nos ama." in lit[-1]["content"]
    m2 = idea.build_messages([], "x", "de", "es", literal="Por eso dio a su Hijo.", input_mode="ambos")
    assert "Traducción literal:\nPor eso dio a su Hijo." in m2[-1]["content"]
    assert idea.clean_output("...") == "" and idea.clean_output("…") == ""
    assert idea.clean_output("<think>x</think>\nDios ama al mundo.") == "Dios ama al mundo."
    assert idea.clean_output("**Frase: Oremos juntos.**") == "Oremos juntos."
    assert idea.clean_output("Idea principal: «La gracia nos salva.»\nPorque…") == "La gracia nos salva."
    # Modelos que "razonan en voz alta" (caso real con qwen3:4b): nunca se muestran como idea
    assert idea.clean_output("Okay, let's tackle this translation request. So, the user wants") == ""
    assert idea.clean_output("The user wants...\n</think>\n\nDios ama al mundo.") == "Dios ama al mundo."


def test_metricas_y_pausa():
    import tempfile
    from pathlib import Path
    import metrics as M
    m = M.Metrics(Path(tempfile.mkdtemp()) / "metrics")
    for _ in range(5):
        m.whisper_step("partial", 4, 0.8)
    assert not m.whisper_overloaded(2.0)                 # va bien: ideas permitidas
    for _ in range(6):
        m.whisper_step("partial", 6, 3.2)
    assert m.whisper_overloaded(2.0)                     # va lento: ideas en pausa
    m.whisper_cost_at -= 25
    assert not m.whisper_overloaded(2.0)                 # silencio: se reanuda
    m.log("idea", ms=4000, result="ok")
    lines = m.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 12 and '"ev": "idea"' in lines[-1]


def test_motor_mlx_eleccion_de_modelo():
    assert s.resolve_mlx_model("turbo") == "mlx-community/whisper-large-v3-turbo"
    assert s.resolve_mlx_model("mlx-community/otro") == "mlx-community/otro"
    if not (s.MLX_SWISS_PATH / "config.json").exists():
        try:
            s.resolve_mlx_model(s.DEFAULT_MODEL)
            raise AssertionError("debía pedir la conversión")
        except SystemExit as exc:
            assert "convert_to_mlx.sh" in str(exc)


def test_detector_de_bucles():
    # Casos reales del contexto corto (bench del 23.11.2026)
    assert s.looks_broken("Liebe und Besonnenheit. Und ich hörte... ... und ich hörte... ... und ich hörte...")
    assert s.looks_broken("Ein Jesus kann ein Jesus auf der Pischung ein Säge ein Säge ein Säge")
    assert s.looks_broken("Ich bitte dich. Du hast siebe. Du hast siebe. Du hast siebe. Du hast siebe.")
    assert s.looks_broken("Hallo", n_tokens=40, max_tokens=40)          # agotó el límite
    # Frases buenas: no se repiten
    assert not s.looks_broken("Denn der Geist, den Gott uns gegeben hat, macht uns nicht.")
    assert not s.looks_broken("Ich lasse vor, darum bitte ich dich, lass Gottes Gabe voll in dir wirksam werden.")
    assert not s.looks_broken("")


def test_puerta_de_volumen():
    # Por defecto (-50 dB) la voz floja de una pestaña con poco volumen PASA
    seg = s.Segmenter(0, 0.5, 6.0, gate_db=-50)
    finals = []
    audio = np.concatenate([sil(1), voice(2, amp=0.012), sil(1)])
    for i in range(0, len(audio), 1600):
        seg.add((audio[i:i + 1600] * 32767).astype(np.int16).tobytes())
        k, a = seg.decide(i / SR)
        if k == "final":
            finals.append(a)
    assert len(finals) == 1 and seg.gated == 0
    # Con una puerta más alta, esa misma frase NO se manda al modelo
    seg = s.Segmenter(0, 0.5, 6.0, gate_db=-30)
    for i in range(0, len(audio), 1600):
        seg.add((audio[i:i + 1600] * 32767).astype(np.int16).tobytes())
        k, _ = seg.decide(i / SR)
        assert k is None
    assert seg.gated == 1
    assert segmenter.level_db(voice(1, amp=0.2)) > -20 > segmenter.level_db(voice(1, amp=0.01))


def test_lista_de_palabras_se_descarta():
    # Fallo documentado por Barnaba: Whisper «lee» el glosario como lista
    assert asr.looks_like_list("Grossrat, Grossrätin, Schäupte, Schöttemberg, Schubstabe, Schutze")
    assert asr.looks_like_list("Matthäus, Markus, Lukas, Johannes, Apostelgeschichte.")
    assert not asr.looks_like_list("Matthäus, Markus und Lukas erzählen, was Jesus tat.")
    assert not asr.looks_like_list("Ja, ich bin sicher, Jesus ist dir begegnet.")
    assert asr.should_drop("Matthäus, Markus, Lukas, Johannes, Römer.")


def test_contexto_frase_anterior():
    largo = "Und Jesus sprach zu ihnen: " + "Folgt mir nach, " * 20 + "und ich mache euch zu Menschenfischern."
    tail = asr.context_tail(largo)
    assert len(tail) <= asr.CONTEXT_CHARS and tail.endswith("Menschenfischern.") and not tail.startswith(" ")
    m = asr.MockTranscriber(context="confirmed")
    assert m.prompt_for("Gott liebt uns.") == "Gott liebt uns."
    assert asr.MockTranscriber().prompt_for("Gott liebt uns.") == ""          # sin --context: nada
    m.prompt_text = "Jesus Christus, Heiliger Geist"
    assert m.prompt_for("Gott liebt uns.") == "Jesus Christus, Heiliger Geist"  # el vocabulario manda


def test_whisper_simulado():
    m = asr.MockTranscriber()
    assert m._run(np.zeros(int(0.1 * SR), dtype=np.float32)) == ""
    assert m._run(np.zeros(2 * SR, dtype=np.float32)) == "Satz 2 mit 2.0 Sekunden."
    assert asr.make_transcriber("mock", "x", None, "de").__class__ is asr.MockTranscriber


def test_dialecto():
    import dialect
    d = dialect.Dialect({"nöd": "nicht", "öppis": "etwas"})
    assert d.apply("Das isch nöd öppis Neues. Nöd jetzt.") == "Das isch nicht etwas Neues. Nicht jetzt."
    assert d.apply("nödig") == "nödig"                                     # solo palabras enteras
    assert dialect.Dialect().apply("nöd") == "nöd"
    assert len(dialect.Dialect.load()) == 0                                # la lista empieza vacía


def test_sugerir_dialecto():
    import evaluate
    pares = [("Das ist nicht gut.", "Das ist nöd gut."), ("Ich weiss es nicht.", "Ich weiss es nöd."),
             ("Er hat etwas gesagt.", "Er hat öppis gesagt.")]
    c = evaluate.dialect_candidates(pares)
    assert c == [("nöd", "nicht", 2)], c


def test_protocolo():
    import protocol as P
    m = P.final(7, "Gott liebt uns.")
    assert m == {"v": 1, "type": "final", "seq": 7, "text": "Gott liebt uns."}
    t = P.translation(7, {"es": "Dios nos ama."}, 0.4321)
    assert t["seq"] == 7 and t["ms"] == 432 and t["tr"]["es"] == "Dios nos ama."
    assert P.parse("no es json") is None and P.parse("[1,2]") is None
    assert P.parse('{"type":"flush"}') == {"type": "flush"}


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print("OK ", t.__name__)
    print(f"{len(tests)} pruebas correctas")
