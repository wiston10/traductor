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
