# Traductor — apuntador para intérpretes

Herramienta gratuita para una organización sin ánimo de lucro. Ayuda a la persona que
**interpreta en vivo** una prédica: mientras el predicador habla (alemán, suizo alemán,
francés o inglés), en la pantalla del intérprete aparece lo que se dice y una traducción
automática al español, a un ritmo que se puede leer. El intérprete lee, corrige y habla.

No usa APIs de pago ni claves: el reconocimiento de voz y la traducción corren en el
navegador o en el propio Mac.

## Cómo funciona

```text
 Directo (YouTube…) o micrófono
            │ audio
            ▼
 ┌──────────────────────────┐   alemán estándar, francés, inglés
 │ Motor de voz             │── Chrome (reconocimiento de Google, necesita internet)
 │                          │── Whisper suizo-alemán (en el Mac, sin internet)
 └──────────────────────────┘
            │ texto original
            ▼
 Traductor integrado de Chrome (en el ordenador) + glosario de la iglesia
            │ texto traducido
            ▼
 Pantalla del intérprete: ritmo de lectura ajustable + línea guía
```

## Estructura

| Carpeta | Qué es | Estado |
|---|---|---|
| `apps/web` | La página del apuntador (un solo `index.html`) | **En uso** |
| `apps/whisper-server` | Servidor local con Whisper ajustado a suizo alemán; también sirve la página | **En uso** |
| `apps/mobile` | App de iPhone (Expo, iOS 26) | En pausa — ver su README |
| `packages/shared` | Tipos e idiomas compartidos de la app móvil | Solo para `apps/mobile` |
| `tests` | Pruebas de la app móvil | Solo para `apps/mobile` |

## Puesta en marcha (Mac con chip Apple)

Una sola vez:
```bash
cd apps/whisper-server
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Cada culto:
```bash
npm start            # o: cd apps/whisper-server && .venv/bin/python server.py
```
Abre **http://localhost:8765** en Google Chrome (versión 138 o posterior, en ordenador).

1. Pega el enlace del directo y pulsa **Mostrar al lado** (opcional).
2. Elige el motor: **Whisper** para suizo alemán; **Chrome** para alemán estándar, francés o inglés.
3. Pulsa **Empezar** y, si usas el audio del directo, comparte la pestaña con **«Compartir audio»**.
4. Ajusta el **ritmo de lectura** y la **línea guía**.

Más detalles: [`apps/web/README.md`](apps/web/README.md) y
[`apps/whisper-server/README.md`](apps/whisper-server/README.md).

## Glosario bíblico

La página trae un glosario incorporado (alemán, francés e inglés → español) con unos
600 nombres bíblicos, libros y términos de iglesia por idioma. Se genera a partir de
Biblias antiguas de dominio público:

```bash
python3 tools/fetch_bibles.py    # una vez: descarga las Biblias a data/bibles/ (no van a git)
python3 tools/build_glossary.py  # genera apps/web/glossary/*.json y apps/whisper-server/vocab/de.txt
```

Para corregir un término, añádelo en **Ajustes → tus términos** (manda sobre el incorporado)
o, si es un error del generador, en `BLACKLIST`/`MODERN` dentro de `tools/build_glossary.py`.

## Pruebas

```bash
npm run test:server   # lógica del servidor Whisper (no carga el modelo)
```

## Privacidad

- Motor **Whisper**: el audio no sale del Mac.
- Motor **Chrome**: el audio se envía a Google para reconocer la voz.
- La traducción siempre se hace en el ordenador. No se guarda nada salvo lo que el
  intérprete descargue con el botón **Descargar**.

## Recomendaciones

- Guarda el proyecto **fuera de iCloud** (por ejemplo `~/dev/traductor`): iCloud puede
  quitar archivos del disco mientras se trabaja.
- La calidad depende sobre todo del audio: mejor un cable desde la mesa de sonido o el
  audio del directo que un micrófono al fondo de la sala.
