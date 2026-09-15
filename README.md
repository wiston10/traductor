# Traductor local

Aplicación móvil enfocada en un flujo de traducción local, sin APIs de pago ni servicios externos.

## Objetivo

Convertir la app actual en un traductor de voz Español → Alemán para sesiones largas, con:

- captura local de audio
- detección de actividad de voz (VAD)
- STT local
- traducción local
- TTS local
- pipeline concurrente con control de backpressure
- transcript persistente local
- métricas de latencia en milisegundos

## Estructura

```text
apps/api      Backend local de diagnóstico y configuración
apps/mobile   App React Native/Expo con el pipeline local
packages/shared  Idiomas, tipos y configuración compartida
```

## Requisitos

- Node.js 22+
- Expo development build para iOS/Android
- Modelos locales descargados antes de iniciar una sesión

### Requisitos específicos del modo real (`offline-real`)

El pipeline real usa exclusivamente frameworks de Apple on-device, sin
servidores, sin API keys y sin conexión a internet en tiempo de ejecución:

| Etapa | Implementación real | Requisito de plataforma |
| --- | --- | --- |
| STT | `SFSpeechRecognizer` con `requiresOnDeviceRecognition = true` | iOS 26.0+, permiso de reconocimiento de voz y micrófono |
| Traducción ES→DE | `Translation` framework de Apple (`TranslationSession`) | iOS 26.0+, paquete de idioma alemán instalado (se solicita en el primer uso) |
| TTS | `AVSpeechSynthesizer` | iOS 26.0+ |

No existe implementación de `whisper.cpp` en este repositorio: `WhisperEngine`
está deliberadamente marcado como *no implementado* (lanza un error explícito
en vez de simular texto) y queda documentado como prioridad futura si
`SFSpeechRecognizer` no fuera suficiente para algún dispositivo/idioma.

`NLLBEngine`/`MarianEngine` (basados en diccionario) fueron evaluados y
eliminados: se decidió usar el framework `Translation` de Apple porque ya
corre on-device de fábrica, sin necesitar convertir/empaquetar un modelo
NLLB/MarianMT a CoreML dentro de esta sesión de trabajo.

## Instalación

```bash
npm install
cp .env.example .env
```

## Ejecutar backend local

```bash
npm run dev:api
```

## Ejecutar móvil

```bash
npm run dev:mobile
```

Para iOS native:

```bash
cd apps/mobile
npx expo run:ios --device
```

## Principio de diseño

La aplicación queda orientada a un pipeline local, sin servicios de pago ni dependencias externas. El flujo se organiza en capas independientes:

- audio capture
- VAD
- STT engine
- transcript manager
- translation queue
- TTS queue
- playback

Cada etapa opera con colas acotadas, backpressure y métricas de latencia. La lógica se mantiene separada de la interfaz.

## `pipelineMode`: `offline-real` vs `demo`

La app expone un `pipelineMode` explícito en `apps/mobile/src/types/pipeline.ts`:

- **`offline-real`** (modo por defecto al iniciar la app): usa exclusivamente
  `TranslationPipeline.ts`, que habla con el módulo nativo real
  (`apps/mobile/modules/offline-pipeline`). Nunca contiene texto de ejemplo,
  nunca usa `Date.now()` para medir latencia, y nunca marca una etapa como
  completa antes de que el evento nativo correspondiente ocurra realmente.
- **`demo`**: usa `apps/mobile/src/pipeline/DemoPipeline.ts`, un módulo
  totalmente separado que reproduce segmentos de ejemplo etiquetados
  `[DEMO]`/`mode: "demo"`. El modo demo **nunca** puede activarse por
  accidente en el pipeline real: no comparten estado, colas ni motores.

`useRealtimeTranslator(pipelineMode)` decide cuál de los dos pipelines
instanciar; el valor por defecto es `"offline-real"`.

## Métricas de latencia (reloj monotónico)

Cada segmento crea su propia `PerformanceTimeline`
(`apps/mobile/src/performance/PerformanceTimeline.ts`), que registra marcas
usando `monotonicNowMs()` (`performance.now()`), nunca `Date.now()`. Las
métricas expuestas son:

```text
sttLatencyMs         = sttFinal - chunkReady
translationLatencyMs = translationComplete - translationStart
ttsLatencyMs         = firstAudio - ttsStart
endToEndLatencyMs    = firstAudio - speechStart
```

Si falta una marca, o si la resta diera negativa (lo que indicaría marcas
fuera de orden), la métrica correspondiente es `null`. Nunca se inventa un
valor ni se permite un número negativo.

## IDs de segmento

`SegmentIdGenerator` (`apps/mobile/src/pipeline/SegmentIdGenerator.ts`)
genera IDs monotónicos `segment-000001`, `segment-000002`, ... únicos durante
toda la sesión. Estos IDs (no timestamps) se usan como `key` de React en la
UI de transcripción.

## Backpressure sin pérdida de segmentos

`PipelineQueue` nunca descarta automáticamente al hacer `push()`.
`BackpressureManager.assess()` sólo recomienda reducir la duración del
próximo segmento capturado y emite una advertencia (`warning`) cuando una
cola se satura o el *lag* de espera supera el umbral — nunca elimina un
segmento en cola. `PipelineQueue.dropOldest(true)` existe únicamente para el
caso en que el usuario haya habilitado explícitamente una política de
recuperación; ningún código del pipeline llama a esto automáticamente.

## Validación manual en dispositivo real (obligatoria antes de declarar "functional")

Ninguna prueba automatizada dentro de este repositorio puede validar por sí
sola que el habla real se transcribe/traduce/reproduce correctamente, porque
eso requiere un micrófono físico, permisos del sistema y los frameworks de
Apple ejecutándose en iOS real. Antes de considerar el proyecto funcional,
un humano debe verificar en un dispositivo/simulador con iOS 26+:

1. Abrir la app; debe iniciar en `pipelineMode: "offline-real"`.
2. Conceder permisos de micrófono y reconocimiento de voz.
3. En el primer uso, aceptar la descarga del paquete de idioma alemán que
   solicita el framework `Translation` de Apple.
4. Decir en voz alta: *"Hoy vamos a estudiar la palabra de Dios."*
5. Confirmar en la UI:
   - Aparece un `partial transcript` mientras se habla.
   - Aparece un `final transcript` en español real (no un texto fijo de
     ejemplo).
   - Aparece una traducción real al alemán, y `originalText !== translatedText`.
   - Se reproduce audio en alemán (TTS) — el marcador `firstAudio` sólo debe
     registrarse cuando el audio realmente empieza a sonar.
   - Las métricas de latencia mostradas son todas `>= 0` o `null` (nunca
     negativas).
6. Repetir varias frases seguidas y confirmar que no aparecen IDs de
   segmento duplicados ni eventos `SPEECH_START` repetidos para la misma
   frase.
7. Para sesiones largas (orden de 5, 30 y 120 minutos hablando de forma
   continua), confirmar con Xcode Instruments: memoria acotada (sin
   crecimiento indefinido), `droppedSegments = 0`, sin transcripciones
   duplicadas, y que el orden de reproducción del audio traducido coincide
   con el orden en que se habló.

Las pruebas automatizadas en `tests/pipeline-endurance.test.ts` simulan la
mecánica de colas/backpressure/IDs para sesiones equivalentes a 5/30/120
minutos (sin drops, sin duplicados, sin latencias negativas), pero **no
sustituyen** el paso 7: no miden memoria/CPU real de iOS ni ejecutan los
frameworks nativos.
