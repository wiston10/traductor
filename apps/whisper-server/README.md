# Servidor Whisper local (suizo alemán)

El reconocimiento de voz de Chrome está pensado para alemán estándar y falla con
el dialecto suizo. Este servidor ejecuta en tu Mac un modelo Whisper ajustado para
suizo alemán, que **escucha dialecto y escribe en alemán estándar**. Después, la
página traduce ese texto al español como siempre.

Gratis, sin claves y el audio no sale del ordenador.

## Requisitos
- Mac con chip Apple (M1 o posterior), 16 GB de RAM recomendados.
- Python 3.10 o posterior.
- La primera vez descarga el modelo (~1,6 GB); después funciona sin internet
  (la traducción de Chrome también es local).

## Instalación (una sola vez)
```bash
cd apps/whisper-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uso
```bash
cd apps/whisper-server
source .venv/bin/activate
python3 server.py
```
Abre **http://localhost:8765** en Chrome (el servidor ya sirve la página).
En la barra elige **Voz: Whisper suizo-alemán** y pulsa **Empezar**.

## Ajustes útiles
| Opción | Por defecto | Qué hace |
|---|---|---|
| `--partial-every 0.7` | 1.0 | Texto provisional más frecuente (más rápido, más carga) |
| `--max-seg 5` | 6 | Corta antes cuando el predicador no hace pausas |
| `--silence 0.4` | 0.5 | Pausa más corta para cerrar frase |
| `--model …` | `Flurin17/whisper-large-v3-turbo-swiss-german` | Probar otro modelo, p. ej. `nizarmichaud/whisper-large-v3-turbo-swissgerman` |
| `--vocab` | apagado | Da a Whisper una lista de nombres bíblicos y términos de iglesia (`vocab/de.txt`) para reconocerlos mejor. Pruébalo y compara |
| `--verbose` | — | Muestra cuánto tarda cada paso |
| `--allow-origin URL` | — | Permitir que otra web (p. ej. la página publicada en GitHub Pages) use el servidor |

Si aparece «Whisper va lento», el Mac no da abasto: sube `--partial-every`
o prueba un Mac más potente.

## Seguridad
Solo acepta conexiones de páginas abiertas en este ordenador (`localhost`). Otra web abierta
en el navegador no puede usar el servidor a escondidas.

## Pruebas
```bash
python3 test_server.py
```
Comprueban los cortes de frase, el descarte de ruidos cortos, la voz con volumen bajo
y el filtro de seguridad, sin cargar el modelo.

## Guardar frases para entrenar (fase 2)

1. En el apuntador, con el motor **Whisper**, activa **💾 Guardar para entrenamiento**
   (siempre con permiso de quien predica; se desactiva solo al recargar la página).
   Cada frase se guarda en `training-data/<fecha_hora>/` (audio WAV + texto). No va a git.
2. Abre **http://localhost:8765/corregir**: escucha cada frase, corrige el texto en
   **alemán estándar** y pulsa **Enter** (guarda y pasa a la siguiente).
   `Alt+R` repite el audio, `Alt+D` descarta (música, ruido, no se entiende).
   Marca 1 de cada 5 cultos como **Prueba**: esos sirven para medir y nunca se entrenan.
3. Mide el acierto real (no carga el modelo):
   ```bash
   .venv/bin/python evaluate.py                 # % de error en directo y palabras que más falla
   .venv/bin/python evaluate.py --model <otro>  # comparar otro modelo con las sesiones de prueba
   .venv/bin/python evaluate.py --model Flurin17/whisper-large-v3-turbo-swiss-german --vocab  # ¿ayuda --vocab?
   ```
4. Cuando haya 10–20 h corregidas, exporta el conjunto para entrenar:
   ```bash
   python3 ../../tools/export_dataset.py        # -> data/dataset/train y data/dataset/test
   ```

## Modo idea (fase 3, experimental)

Un modelo de lenguaje **local** resume en una frase corta la idea de lo que se está diciendo,
teniendo en cuenta las frases anteriores. No sustituye a la traducción literal: va al lado.

1. Instala **Ollama** (gratis): https://ollama.com — y descarga un modelo pequeño (~3 GB):
   ```bash
   ollama pull gemma3:4b
   ```
   Importante: usa un modelo **sin razonamiento**. `qwen3:4b` «piensa en voz alta» en inglés
   antes de responder (probado: ~7 s por idea y sin respuesta útil); no sirve en directo.
2. Arranca el servidor como siempre. En el apuntador, **Ver:** «Traducción + 💡 idea» o «Solo 💡 ideas».
3. Mide en tu Mac cuánto tarda y qué escribe:
   ```bash
   .venv/bin/python bench_idea.py                     # con gemma3:4b
   .venv/bin/python bench_idea.py --model llama3.2:3b # comparar con otro sin razonamiento
   ```
   Por defecto compara dos formas: el modelo recibe **solo la traducción literal** (la opción por
   defecto del servidor) u **original + traducción literal** (`--idea-input ambos`).
   Resultado con gemma3:4b en un MacBook Air M3 (23.11.2026): «solo literal» acertó 7 de 8 sin
   inventar nada; «original + literal» 5 de 8 y se adelantó a una conclusión. Unos 4–5 s por idea;
   con el Mac caliente y Whisper a la vez, cuenta con más.
   Para usar otro modelo en directo: `python3 server.py --idea-model llama3.2:3b`.

Cosas a saber:
- Funciona con los dos motores de voz (Chrome y Whisper) y con alemán, francés e inglés.
- Es **más lento** que la traducción literal (en un M3 de 16 GB, del orden de 1–3 s por idea; mídelo).
  Si llegan frases mientras piensa, las agrupa en la siguiente idea: nunca se forma cola.
- En un Mac de 16 GB compite con Whisper por la memoria y la gráfica. Si aparece «Whisper va lento»,
  vuelve a la vista «Traducción».
- Puede equivocarse o simplificar de más: es una ayuda, no una fuente. Pruébalo antes de usarlo un domingo.
