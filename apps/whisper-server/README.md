# Servidor Whisper local (suizo alemán)

El reconocimiento de voz de Chrome está pensado para alemán estándar y falla con
el dialecto suizo. Este servidor ejecuta en tu Mac un modelo Whisper ajustado para
suizo alemán, que **escucha dialecto y escribe en alemán estándar**. Después traduce
cada frase con **NLLB-200** (también en el Mac) a los idiomas que pida la página; si NLLB
no está instalado, traduce Chrome como antes.

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
| `--partial-every 1` | 0 (apagado) | Texto provisional (en un M3 satura el Mac; ver «Configuración recomendada») |
| `--max-seg 5` | 6 | Corta antes cuando el predicador no hace pausas |
| `--silence 0.4` | 0.5 | Pausa más corta para cerrar frase |
| `--model …` | `Flurin17/whisper-large-v3-turbo-swiss-german` | Probar otro modelo, p. ej. `nizarmichaud/whisper-large-v3-turbo-swissgerman` |
| `--vocab` | apagado | Lista de nombres bíblicos para Whisper (`vocab/de.txt`). **Medir antes**: una lista con comas puede hacer que Whisper invente listas (las frases así se descartan solas) |
| `--gate-db -45` | -50 | Puerta de volumen: frases más flojas no se mandan al modelo. `-200` la apaga |
| `--beam 3` | 1 | Búsqueda más amplia en frases definitivas: quizá más acierto, seguro más lento. Medir |
| `--context confirmed` | none | Da a Whisper el final de la frase anterior como contexto. Medir |
| `--translate off` | auto | Traducción NLLB en el servidor (auto = si está instalada) |
| `--mt-beams 1` | 2 | Traducción más rápida (algo menos cuidada) |
| `--engine mock` | torch | Whisper **simulado**: sin modelo, para probar todo lo demás |
| `--verbose` | — | Muestra cuánto tarda cada paso |
| `--allow-origin URL` | — | Permitir que otra web (p. ej. la página publicada en GitHub Pages) use el servidor |

Si aparece «Whisper va lento», el Mac no da abasto: sube `--partial-every`
o prueba un Mac más potente.

## Seguridad
Solo acepta conexiones de páginas abiertas en este ordenador (`localhost`). Otra web abierta
en el navegador no puede usar el servidor a escondidas.

## Pruebas
```bash
npm test                      # desde la raíz: páginas + servidor
.venv/bin/python run_tests.py # solo el servidor
```
No cargan ningún modelo (Whisper y traductor simulados): cortes de frase, puerta de volumen,
filtros, glosario, frases fijas, protocolo y una prueba de punta a punta por WebSocket.
Las mismas pruebas corren solas en GitHub en cada push (`.github/workflows/ci.yml`).

## Cómo está organizado

| Archivo | Qué hace |
|---|---|
| `server.py` | Web y WebSocket: une todo lo demás |
| `segmenter.py` | Corta el audio en frases (+ puerta de volumen) |
| `asr.py` | Motores Whisper (torch, mlx, simulado) y filtros del texto |
| `translate.py` | Traducción NLLB, glosario y frases fijas (`vocab/frases-fijas.json`) |
| `dialect.py` | Dialecto → alemán estándar (`vocab/dialecto-de.json`, revisado a mano) |
| `rooms.py` | La sala: PIN, pases, reparto a los móviles por idioma, reconexión |
| `protocol.py` | Formato de los mensajes: versión y número de frase |
| `net.py` | Qué páginas pueden conectarse |

## Traducción en el servidor (NLLB-200, 15 idiomas)

Un solo modelo traduce entre los 15 idiomas más hablados en cualquier dirección: inglés, chino,
hindi, español, árabe, francés, bengalí, portugués, indonesio, urdu, ruso, alemán, japonés,
maratí y vietnamita. Corre en el procesador, así la tarjeta gráfica queda para Whisper.
**Licencia CC BY-NC 4.0: solo uso no comercial** (ver `AVISO_LICENCIAS.md`).

```bash
npm run setup:nllb   # una vez: instala CTranslate2 y convierte el modelo (~600 MB)
npm run bench:mt     # ¿cuánto tarda en traducir a 1, 3, 5 y 15 idiomas? Objetivo: < 2 s con 15
npm run bench:mt -- --comparar   # prueba procesador/tarjeta gráfica, beams y núcleos
npm start            # ya traduce solo
```

Medido el 24.11.2026 en un MacBook Air M3 (8 frases, 14 idiomas de destino):

| Dónde | Beams | Núcleos | Media por frase | Peor |
|---|---|---|---|---|
| **Procesador (por defecto)** | **1** | **4** | **1,89 s** | 2,81 s |
| Procesador | 2 | 4 | 3,08 s | 4,36 s |
| Procesador | 1 | 8 | 2,29 s | 3,39 s |
| Tarjeta gráfica (`--mt-device mps`) | 1 | 4 | 1,62 s | 2,45 s |

Se queda el procesador: la tarjeta gráfica es solo 0,27 s más rápida y la comparte Whisper.
Probar `--mt-device mps` solo en un culto de prueba, mirando con `report.py` que Whisper no se ralentiza.
Con un solo idioma (el intérprete) tarda unos 0,6 s.
La página pide al servidor el idioma que tenga elegido como destino; si el servidor no puede,
traduce Chrome como antes. Solo se traducen los idiomas que alguien pide.
Antes de traducir se aplica el glosario bíblico (hoy solo hacia el español) y las frases fijas
(«Amen.», «Halleluja!») en los idiomas con forma revisada.

## Medir opciones de transcripción (paso 2 del plan)

Con al menos 50 frases corregidas y la sesión marcada como **Prueba**:
```bash
.venv/bin/python evaluate.py                                   # punto de partida (en directo)
.venv/bin/python evaluate.py --model suizo                     # volver a transcribir, base
.venv/bin/python evaluate.py --model suizo --beam 3            # ¿beam ayuda? ¿cuánto más lento?
.venv/bin/python evaluate.py --model suizo --context confirmed # ¿ayuda la frase anterior?
.venv/bin/python evaluate.py --model suizo --vocab             # ¿ayuda el vocabulario?
.venv/bin/python evaluate.py --model suizo --gate-db -45       # ¿la puerta quita frases buenas?
.venv/bin/python evaluate.py --sugerir-dialecto                # palabras de dialecto que corriges siempre
```
Cada línea dice el % de error y el tiempo medio por frase. Regla: se adopta una opción solo si
baja el error sin subir el tiempo más de un 20 %.

## Sala para los móviles (paso 5)

Los oyentes siguen la prédica en su móvil, cada uno en su idioma, sin instalar nada.

```bash
npm run start:sala
```
1. En el Mac, abre **http://localhost:8765/sala**: muestra el **código QR** y el **PIN** en grande
   (para proyectarlo o imprimirlo) y cuántos móviles hay conectados y en qué idiomas.
2. Los oyentes, **en la misma red Wi-Fi que el Mac**, escanean el QR (o abren la dirección y escriben el PIN)
   y eligen su idioma. Pueden agrandar la letra y ver también el original.
3. El operador usa el apuntador como siempre (http://localhost:8765) y pulsa **Empezar**: cada frase
   llega a los móviles; la traducción, ~2 s después.

Cómo funciona por dentro:
- Solo se traducen los idiomas que alguien escucha, todos de una vez (un lote).
- Cada frase lleva un número: un móvil que pierde la conexión recibe al volver solo lo que se perdió.
- Un solo socket por móvil (si el mismo móvil vuelve a entrar, se cierra el anterior).
- El PIN va dentro del QR. Después el móvil guarda un **pase firmado** (secreto propio del servidor en
  `.secret-sala`, no va a git) válido 6 h. Tras 8 PIN fallidos, esa dirección espera 5 minutos.
- **Seguridad:** desde la red solo se puede abrir la página del oyente y su conexión. El audio, la
  corrección, las frases guardadas y el modo idea solo funcionan desde el propio Mac.
- La primera vez, macOS preguntará si Python puede aceptar conexiones entrantes: **Permitir**.
- El PIN cambia en cada arranque. Para fijarlo: `npm run start:sala -- --pin 2026`.
- Sin https (red local) el móvil puede apagar la pantalla; los oyentes pueden subir el tiempo de bloqueo.

Medir el objetivo del paso 5 (90 % de las frases en menos de 3 s) después de un culto de prueba:
`.venv/bin/python report.py` → línea «Retraso hasta la traducción». Se mide desde que el servidor
cierra la frase (tras la pausa de 0,5 s) hasta que la traducción sale hacia los móviles.

## Prédicas en otros idiomas

El modelo suizo solo entiende alemán y suizo alemán. Para una prédica en inglés, español,
francés u otro idioma, arranca con el Whisper general e indica el idioma:
```bash
npm start -- --model turbo --language en
```

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
   .venv/bin/python evaluate.py --model suizo --vocab  # ¿ayuda --vocab? (más opciones abajo)
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

## Rendimiento y protección

- El servidor guarda un registro de rendimiento en `metrics/` (no va a git; desactivar con `--no-metrics`).
  `.venv/bin/python report.py` lo resume por tramos de 10 minutos y avisa si el Mac se fue calentando.
- **Protección:** si Whisper tarda más de 2 s por paso de forma sostenida, el modo idea se pausa solo
  («⏸ Ideas en pausa») y se reanuda cuando el Mac se recupera. Cambiar el umbral: `--idea-pause 3`.

## Configuración recomendada (medida el 23.11.2026 en un MacBook Air M3, 16 GB)

| Motor | Tiempo por frase | Acierto |
|---|---|---|
| **PyTorch + modelo suizo (por defecto)** | **~1,7 s** | **el mejor** |
| MLX + modelo suizo | ~2,0 s | igual |
| MLX + modelo suizo + contexto corto | ~1,3 s | peor (palabras cambiadas, frases duplicadas) |
| MLX + turbo normal + contexto corto | ~0,7 s | bastante peor (mezcla idiomas) |

Conclusión: en este Mac se queda **PyTorch + modelo suizo**. El texto provisional está **desactivado por
defecto** (duplicaba el trabajo y el Mac se quedaba atrás); cada frase aparece entera ~2 s después de decirse.
En un Mac más potente se puede activar: `npm start -- --partial-every 1`.

## Motor MLX (más rápido en Mac) — opcional, en pruebas

El motor actual (PyTorch) es el más lento en Mac: en comparativas públicas con el mismo modelo,
MLX (el sistema de Apple para sus chips) fue varias veces más rápido. En nuestra prueba de 17 min,
PyTorch tardó ~2,3 s por paso en un MacBook Air M3: demasiado.

**Probar en 2 comandos** (desde la carpeta principal del proyecto):
```bash
npm run setup:mlx   # 1. instala MLX y convierte el modelo suizo (una vez, ~5 min)
npm run bench       # 2. compara los motores con el mismo audio
```
`npm run bench` no necesita que prepares nada: usa las frases guardadas para entrenamiento o, si no
hay, genera frases de prédica en alemán con la voz del Mac (sirve para medir la velocidad).
Con una grabación propia (cualquier formato): `cd apps/whisper-server && .venv/bin/python bench_asr.py --audio grabacion.m4a`.

Si MLX gana, úsalo en directo:  `npm start -- --engine mlx`

**Contexto corto (experimental, `--audio-ctx auto`)**: Whisper siempre procesa bloques de 30 s, aunque la
frase dure 5 s (el resto es silencio de relleno). Con `auto` solo procesa la duración real + 1 s: mucho
menos cálculo. Puede afectar al acierto: `npm run bench` lo compara (filas «turbo-corto» y «swiss-corto»).
En directo: `npm start -- --engine mlx --audio-ctx auto`.

Sin convertir nada también puedes probar el Whisper turbo **normal** (entiende suizo alemán y escribe
alemán estándar, aunque acierta menos que el ajustado): `npm start -- --engine mlx --model turbo`.

Para medir el acierto (no solo la velocidad) con frases corregidas:
`.venv/bin/python evaluate.py --engine mlx --model Flurin17/whisper-large-v3-turbo-swiss-german`

PyTorch sigue siendo el motor por defecto hasta que MLX se valide en vuestro Mac.
