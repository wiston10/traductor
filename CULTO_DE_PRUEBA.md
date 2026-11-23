# Culto de prueba (modo sombra) — lista de comprobación

El intérprete trabaja **como siempre**. Otra persona usa la herramienta a su lado y observa.
La herramienta **no** debe ser imprescindible: si falla, nadie lo nota.

## Día antes
- [ ] Pedir permiso a quien predica para guardar el audio (solo si se va a usar «Guardar para entrenamiento»).
- [ ] Ollama instalado y modelo descargado: `ollama pull gemma3:4b`.
- [ ] Prueba rápida en casa: `npm start`, abrir http://localhost:8765, 2 minutos con un vídeo de YouTube.

## 30 minutos antes
- [ ] Mac **enchufado**, sobre una superficie dura y fresca (no sobre tela). Cerrar programas que no se usen.
- [ ] Abrir **Ollama**.
- [ ] Terminal: `cd ~/Documents/traductor && npm start` → esperar «Modelo listo».
- [ ] Chrome: **http://localhost:8765**
  - Idiomas: **Alemán (Suiza)** → **Español**
  - Voz: **Whisper suizo-alemán** · Audio: **De la transmisión** o **Micrófono**
  - Ver: **Traducción + 💡 idea** · Lectura: ~170 pal/min · Línea guía activada
  - (opcional, con permiso) **💾 Guardar para entrenamiento**
- [ ] Prueba de 1 minuto con el audio real (alabanza o anuncios): aparece texto y traducción.

## Durante el culto — apuntar solo esto
| Hora | Qué pasó |
|---|---|
| | Idea que dice algo que el predicador **no** dijo (copiar la idea) |
| | Aparece «Whisper va lento» o «Ideas en pausa» |
| | Cualquier otra cosa rara |

(Tiempos, pausas y lentitud **se registran solos**: no hace falta apuntarlos.)

## Después
1. Informe automático de rendimiento:
   ```bash
   cd ~/Documents/traductor/apps/whisper-server
   .venv/bin/python report.py
   ```
2. Si se guardaron frases: corregirlas en http://localhost:8765/corregir (marcar este culto como **Prueba**)
   y medir el acierto de Whisper:
   ```bash
   .venv/bin/python evaluate.py
   ```
3. Pregunta al intérprete (1–5): ¿le ayudó la traducción literal? ¿y las ideas? ¿qué cambiaría?
4. Comparte con el equipo de desarrollo: la salida de `report.py`, la de `evaluate.py`, las notas y la valoración.
