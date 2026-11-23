#!/usr/bin/env python3
"""Pruebas rápidas del servidor (no cargan el modelo). Uso: python3 test_server.py"""
import numpy as np

import server as s

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


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print("OK ", t.__name__)
    print(f"{len(tests)} pruebas correctas")
